"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAccount, useWalletClient } from "wagmi";
import { useQuery } from "@tanstack/react-query";
import { useSignal, usePurchaseSignal, useSignalNotionalFilled, useEscrowBalance, useDepositEscrow, useWalletUsdcBalance, useMutationGate, humanizeError, getReadProvider } from "@/lib/hooks";
import { getEscrowContract, ADDRESSES, ACCOUNT_ABI } from "@/lib/contracts";
import { ethers } from "ethers";
import { discoverValidatorClients, checkLinesViaSubnet, type ValidatorClient } from "@/lib/api";
import { decrypt, fromHex, bigIntToKey, reconstructSecret } from "@/lib/crypto";
import type { ShamirShare } from "@/lib/crypto";
import { useActiveSignals } from "@/lib/hooks/useSignals";
import { useAuditHistory } from "@/lib/hooks/useAuditHistory";
import { usePurchaseHistory } from "@/lib/hooks/usePurchaseHistory";
import QualityScore from "@/components/QualityScore";
import { triggerOnboardingRefresh } from "@/components/OnboardingChecklist";
import { txUrl } from "@/lib/explorer";
import {
  SignalStatus,
  signalStatusLabel,
  formatBps,
  formatUsdc,
  parseUsdc,
  truncateAddress,
} from "@/lib/types";
import type { CandidateLine, BookmakerAvailability, CheckResponse } from "@/lib/api";
import { decoyLineToCandidateLine, parseLine, formatLine, sportLabel, formatOdds, usesDecimalOdds } from "@/lib/odds";
import { savePurchasedSignal } from "@/lib/preferences";
import BookPreferences, { ALL_BOOK_KEYS } from "@/components/BookPreferences";
import { isQuorumStrictFor } from "@/lib/featureFlags";
import { callWithQuorumOrFirst } from "@/lib/validatorQuorum";

type PurchaseStep =
  | "idle"
  | "checking_lines"
  | "purchasing_validator"
  | "purchasing_chain"
  | "collecting_shares"
  | "decrypting"
  | "complete"
  | "error"
  | "recovering";

// Persist in-progress purchase state so it survives page refresh.
// After the on-chain TX lands (USDC deducted), we save the signal ID
// and buyer address. On mount, if we find incomplete state, we skip
// straight to share collection and decryption.
const PURCHASE_STATE_KEY = "djinn_purchase_pending";

interface PendingPurchase {
  signalId: string;
  buyer: string;
  timestamp: number;
}

/** Default Shamir threshold when we cannot read it authoritatively from
 * validators. Matches the SHAMIR_MIN=2 bootstrap value on the validator
 * side (see project memory); using 3 here would ask for more shares than
 * most current signals actually require. */
const DEFAULT_SHAMIR_THRESHOLD = 2;

interface CollectSharesOptions {
  /** Maximum number of retry rounds after the initial attempt. */
  maxRetries?: number;
  /** Per-round backoff in ms. Indexed by attempt number (0-based). */
  retryDelaysMs?: number[];
  /** Per-call timeout in ms. */
  perCallTimeoutMs?: number;
  /** Already-collected shares to skip re-querying the same x-coordinate. */
  existingShares?: ShamirShare[];
  /** Called before each retry so the UI can surface "retry N of M" state. */
  onProgress?: (collected: number, needed: number, attempt: number) => void;
}

/** Collect enough Shamir shares from validators to meet a threshold.
 *
 * Runs a race of /purchase-signal calls across every discovered
 * validator. Re-queries the same endpoint on retry: the validator's
 * purchase flow is idempotent for already-paid buyers (see
 * is_payment_consumed in the validator purchase orchestrator), so
 * re-sending does NOT double-charge or re-run MPC — it just returns
 * the same released share. That makes the retry loop safe to run
 * aggressively.
 *
 * Threshold is looked up via shareInfo on the first successful
 * response and never defaults above DEFAULT_SHAMIR_THRESHOLD so we
 * don't ask for more shares than signals actually have.
 *
 * Returns once we hit threshold OR exhaust retries. On timeout the
 * collected shares so far are returned with the error, so callers
 * can still attempt reconstruction if they happen to have enough.
 */
async function collectSharesWithRetry(
  validators: ValidatorClient[],
  signalId: string,
  purchaseReq: {
    buyer_address: string;
    sportsbook: string;
    available_indices: number[];
    buyer_signature: string;
  },
  opts: CollectSharesOptions = {},
): Promise<{
  shares: ShamirShare[];
  threshold: number;
  error: string | null;
}> {
  const maxRetries = opts.maxRetries ?? 4;
  const retryDelaysMs = opts.retryDelaysMs ?? [2000, 4000, 6000, 8000];
  const perCallTimeoutMs = opts.perCallTimeoutMs ?? 15_000;
  const shares: ShamirShare[] = opts.existingShares
    ? [...opts.existingShares]
    : [];

  // Query the threshold up front from whichever validator answers
  // first. We fall back to DEFAULT_SHAMIR_THRESHOLD if every validator
  // fails, which matches SHAMIR_MIN on the validator side.
  let threshold = DEFAULT_SHAMIR_THRESHOLD;
  try {
    const infoResult = await Promise.any(
      validators.map((v) =>
        v.shareInfo(signalId).then((r) => r.shamir_threshold),
      ),
    );
    if (infoResult >= 2 && infoResult <= 7) {
      threshold = infoResult;
    }
  } catch {
    // Fallback used
  }

  const runOneRound = async () => {
    const results = await Promise.allSettled(
      validators.map((v) =>
        Promise.race([
          v.purchaseSignal(signalId, purchaseReq),
          new Promise<never>((_, reject) =>
            setTimeout(
              () => reject(new Error("share collection timeout")),
              perCallTimeoutMs,
            ),
          ),
        ]),
      ),
    );
    for (const result of results) {
      if (
        result.status === "fulfilled" &&
        result.value?.available &&
        result.value.encrypted_key_share &&
        result.value.share_x != null
      ) {
        const x = result.value.share_x;
        if (!shares.some((s) => s.x === x)) {
          shares.push({
            x,
            y: BigInt("0x" + result.value.encrypted_key_share),
          });
        }
      }
    }
  };

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (shares.length >= threshold) break;
    if (attempt > 0) {
      const delay = retryDelaysMs[attempt - 1] ?? retryDelaysMs[retryDelaysMs.length - 1];
      await new Promise((r) => setTimeout(r, delay));
    }
    opts.onProgress?.(shares.length, threshold, attempt);
    try {
      await runOneRound();
    } catch {
      // One round's worth of failures should never block further
      // retries; we only report failure when we've exhausted attempts
      // AND still don't have threshold shares.
    }
  }

  return {
    shares,
    threshold,
    error:
      shares.length >= threshold
        ? null
        : `collected ${shares.length} of ${threshold} required shares`,
  };
}

function savePendingPurchase(signalId: string, buyer: string) {
  try {
    localStorage.setItem(
      PURCHASE_STATE_KEY,
      JSON.stringify({ signalId, buyer, timestamp: Date.now() } satisfies PendingPurchase),
    );
  } catch { /* quota exceeded or SSR */ }
}

function loadPendingPurchase(): PendingPurchase | null {
  try {
    const raw = localStorage.getItem(PURCHASE_STATE_KEY);
    if (!raw) return null;
    const parsed: PendingPurchase = JSON.parse(raw);
    // Expire after 1 hour (shares may no longer be available)
    if (Date.now() - parsed.timestamp > 3_600_000) {
      localStorage.removeItem(PURCHASE_STATE_KEY);
      return null;
    }
    return parsed;
  } catch {
    // Corrupted localStorage entry; clear it and return default
    try { localStorage.removeItem(PURCHASE_STATE_KEY); } catch { /* SSR */ }
    return null;
  }
}

function clearPendingPurchase() {
  try { localStorage.removeItem(PURCHASE_STATE_KEY); } catch { /* SSR */ }
}

export default function PurchaseSignal() {
  const searchParams = useSearchParams();
  const idStr = searchParams.get("id");
  const router = useRouter();
  const { isConnected, address } = useAccount();
  const { data: walletClient } = useWalletClient();
  let signalId: bigint | undefined;
  try {
    signalId = idStr ? BigInt(idStr) : undefined;
  } catch {
    // Invalid signal ID in URL — will show "not found" via useSignal
  }
  const { signal, loading: signalLoading, error: signalError } =
    useSignal(signalId);
  const { purchase, loading: purchaseLoading, error: purchaseError, txHash } =
    usePurchaseSignal();
  const { filled: notionalFilled } = useSignalNotionalFilled(signalId?.toString());
  const { balance: escrowBalance, refresh: refreshEscrow } = useEscrowBalance(address);
  const { deposit: depositEscrow, loading: depositLoading } = useDepositEscrow();
  const { balance: walletUsdc } = useWalletUsdcBalance(address);
  const checkPause = useMutationGate();
  const [depositAmt, setDepositAmt] = useState("");
  const [depositMsg, setDepositMsg] = useState<string | null>(null);

  // Fetch genius stats for sidebar
  const geniusAddress = signal?.genius;
  // Load genius stats lazily (not critical for purchase flow)
  const [showGeniusStats, setShowGeniusStats] = useState(false);
  useEffect(() => {
    // Delay loading genius stats to prioritize purchase-critical data
    const t = setTimeout(() => setShowGeniusStats(true), 3000);
    return () => clearTimeout(t);
  }, []);
  const { signals: geniusSignals } = useActiveSignals(
    undefined,
    showGeniusStats ? geniusAddress : undefined,
  );
  const { audits: geniusAudits, aggregateQualityScore } =
    useAuditHistory(showGeniusStats ? geniusAddress : undefined);

  // Buyer outcome panel: when the connected wallet has purchased this
  // signal, look up the per-purchase outcome on-chain so the user sees
  // win/loss/void instead of generic "no longer available" messaging
  // (user-report #34). The lookup runs only when both wallet and signal
  // are loaded; the cache key matches usePurchaseHistory so the events
  // fetch is deduped with the dashboard.
  const { purchases: buyerPurchases } = usePurchaseHistory(address);
  const matchedPurchase = useMemo(() => {
    if (!signalId) return null;
    const sid = signalId.toString();
    return buyerPurchases.find((p) => p.signalId === sid) ?? null;
  }, [buyerPurchases, signalId]);
  const purchaseOutcomeQuery = useQuery({
    queryKey: ["purchase-outcome", matchedPurchase?.purchaseId ?? "none"] as const,
    queryFn: async () => {
      if (!matchedPurchase || !signal?.genius || !address || !ADDRESSES.account) {
        return null;
      }
      const provider = getReadProvider();
      const contract = new ethers.Contract(ADDRESSES.account, ACCOUNT_ABI, provider);
      const [outcomeRaw, audited] = await Promise.all([
        contract.getOutcome(signal.genius, address, matchedPurchase.purchaseId),
        contract.isPurchaseAudited(matchedPurchase.purchaseId),
      ]);
      return { outcome: Number(outcomeRaw), audited: Boolean(audited) };
    },
    enabled: Boolean(matchedPurchase && signal?.genius && address && ADDRESSES.account),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const [notional, setNotional] = useState("");
  const [step, setStep] = useState<PurchaseStep>("idle");
  const [stepError, setStepError] = useState<string | null>(null);
  const [decryptedPick, setDecryptedPick] = useState<{
    realIndex: number;
    pick: string;
    /** Committed minimum odds in decimal form (e.g., 1.909 for -110). Set at
     * signal creation time by the genius. The current market must meet or
     * exceed this price for the line to be executable. */
    minOdds?: number;
    /** Same committed minimum in American form, for display (e.g., "-110"). */
    minOddsAmerican?: string | null;
  } | null>(null);
  const [availableIndices, setAvailableIndices] = useState<number[]>([]);
  const [marketOdds, setMarketOdds] = useState<number | null>(null);
  const [bestBookmaker, setBestBookmaker] = useState<BookmakerAvailability | null>(null);
  const [realLineBooks, setRealLineBooks] = useState<BookmakerAvailability[]>([]);
  const purchaseInFlight = useRef(false);
  const purchaseBtnRef = useRef<HTMLButtonElement>(null);
  const [purchaseBtnVisible, setPurchaseBtnVisible] = useState(false);
  const checkResultRef = useRef<CheckResponse | null>(null);
  // Detect v2 signal (lines stored off-chain, identified by non-zero linesHash)
  const isV2 = signal?.linesHash != null && signal.linesHash !== "0x" + "0".repeat(64);

  // Pre-check line availability (one-shot on signal load). v2 signals skip the
  // client-side check because validators enforce line availability server-side.
  // Three-state: true = at least one line available, false = all unavailable
  // (with a reason), null = not yet checked / could not check (don't block).
  const linesCheckQuery = useQuery<{ available: boolean | null; reason: string | null }>({
    queryKey: ["idiot-signal-lines-check", idStr ?? "none"] as const,
    queryFn: async () => {
      if (!signal) return { available: null, reason: null };
      if (signal.linesHash && signal.linesHash !== "0x" + "0".repeat(64)) {
        return { available: true, reason: null };
      }
      if (!signal.decoyLines?.length) return { available: null, reason: null };
      const candidateLines: CandidateLine[] = signal.decoyLines.map(
        (raw, i) => decoyLineToCandidateLine(raw, i + 1, signal.sport, idStr ?? ""),
      );
      const result = await checkLinesViaSubnet({ lines: candidateLines });
      if (result.available_indices.length > 0) {
        return { available: true, reason: null };
      }
      const reasons = result.results
        .map((r) => (r as unknown as Record<string, unknown>).unavailable_reason as string | undefined)
        .filter(Boolean);
      const unique = [...new Set(reasons)];
      let reason: string;
      if (unique.includes("game_started")) {
        reason = "The game for this signal has started. Lines are no longer available at sportsbooks.";
      } else if (unique.includes("line_moved")) {
        reason = "The lines for this signal have moved and are no longer available.";
      } else {
        reason = "Lines are temporarily unavailable at sportsbooks. Try again shortly.";
      }
      return { available: false, reason };
    },
    enabled: Boolean(signal && !signalLoading),
    staleTime: 30_000,
    retry: false,
  });
  const linesAvailable: boolean | null = linesCheckQuery.isError
    ? null
    : linesCheckQuery.data?.available ?? null;
  const linesReason: string | null = linesCheckQuery.data?.reason ?? null;

  // Poll validators to see if any still hold shares for this signal. 15s
  // cadence. refetchIntervalInBackground: false pauses while the tab is
  // hidden; refetchOnWindowFocus (default true) refreshes on re-focus. Error
  // fallback is "true" (assume available) to avoid blocking purchase on a
  // transient network blip.
  const sharesAvailableQuery = useQuery<boolean>({
    queryKey: ["idiot-signal-shares-available", signalId?.toString() ?? "none"] as const,
    queryFn: async () => {
      const validators = await discoverValidatorClients();
      const probes = await Promise.allSettled(
        validators.map(async (v) => {
          const res = await fetch(`${v.baseUrl}/v1/signal/${signalId}/status`, {
            signal: AbortSignal.timeout(5000),
          });
          if (!res.ok) throw new Error(`${res.status}`);
          return res.json();
        }),
      );
      return probes.some(
        (r) => r.status === "fulfilled" && (r.value as { has_shares?: boolean })?.has_shares,
      );
    },
    enabled: Boolean(signalId && !signalLoading),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    staleTime: 7_500,
    retry: false,
  });
  const signalAvailable: boolean | null = sharesAvailableQuery.isError
    ? true
    : sharesAvailableQuery.data ?? null;

  // Hide sticky mobile bar when the form submit button scrolls into view
  useEffect(() => {
    const el = purchaseBtnRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setPurchaseBtnVisible(entry.isIntersecting),
      { threshold: 0.5 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [step]);

  // Recovery: if user refreshed after on-chain purchase but before
  // decryption, OR clicked the "Retry decryption" button after an earlier
  // share-collection failure, resume share collection + decryption.
  //
  // This is a single code path used by both the auto-on-mount recovery
  // effect and the explicit retry button, so behavior stays consistent.
  const runDecryptionRecovery = async () => {
    if (!signalId || !address || !signal) return;
    setStep("recovering");
    setStepError(null);
    try {
      const validators = await discoverValidatorClients();
      // v1723: buyer_signature is now mandatory on validators. Reload from
      // sessionStorage cache (populated by the original purchase flow); if
      // missing, sign now so the share-recovery retry path passes the gate.
      let buyerSig = "";
      const sigCacheKey = `djinn:buyerSig:${address.toLowerCase()}:${signalId}`;
      try {
        const cached = sessionStorage.getItem(sigCacheKey);
        if (cached) buyerSig = cached;
      } catch {}
      if (!buyerSig && walletClient) {
        try {
          buyerSig = await walletClient.signMessage({
            message: `djinn:purchase:${signalId}`,
          });
          try { sessionStorage.setItem(sigCacheKey, buyerSig); } catch {}
        } catch {
          // signing rejected — proceed with empty sig; validators with
          // DJINN_ALLOW_UNSIGNED_PURCHASE=1 will still serve us
        }
      }
      const purchaseReq = {
        buyer_address: address,
        sportsbook: "",
        available_indices: [] as number[],
        buyer_signature: buyerSig,
      };

      const { shares, threshold, error } = await collectSharesWithRetry(
        validators,
        signalId.toString(),
        purchaseReq,
        {
          onProgress: (got, need, attempt) => {
            console.log(
              `[recovery] share collection attempt ${attempt + 1}: ${got}/${need} shares`,
            );
          },
        },
      );

      if (error || shares.length < threshold) {
        setStepError(
          `Couldn't collect enough decryption keys (${shares.length}/${threshold}). ` +
          "Your purchase is safe on-chain — nothing was double-charged. " +
          "Click \"Retry decryption\" below to try again, or come back in a minute.",
        );
        setStep("idle");
        return;
      }

      const reconstructedBigInt = reconstructSecret(shares);
      const keyBytes = bigIntToKey(reconstructedBigInt);
      const blobBytes = signal.encryptedBlob.startsWith("0x")
        ? signal.encryptedBlob.slice(2)
        : signal.encryptedBlob;
      const blobStr = new TextDecoder().decode(fromHex(blobBytes));
      const colonIdx = blobStr.indexOf(":");
      if (colonIdx === -1) throw new Error("Invalid encrypted blob format");
      const iv = blobStr.slice(0, colonIdx);
      const ciphertext = blobStr.slice(colonIdx + 1);
      const plaintext = await decrypt(ciphertext, iv, keyBytes);
      const parsed = JSON.parse(plaintext);

      setDecryptedPick(parsed);
      clearPendingPurchase();
      savePurchasedSignal(address, {
        signalId: signalId.toString(),
        realIndex: parsed.realIndex,
        pick: parsed.pick,
        sportsbook: "",
        notional: "0",
        purchasedAt: Math.floor(Date.now() / 1000),
      });
      setStep("complete");
    } catch (err) {
      setStepError(
        `Decryption recovery hit an error: ${err instanceof Error ? err.message : "unknown"}. ` +
        "Your payment is recorded on-chain — nothing was lost. " +
        "Click \"Retry decryption\" to try again.",
      );
      setStep("idle");
    }
  };

  // Auto-recovery on mount: if pending-purchase state exists (user
  // refreshed between on-chain payment and decryption), run the recovery
  // exactly once.
  const recoveryAttemptedRef = useRef(false);
  useEffect(() => {
    if (!signalId || !isConnected || !address || !signal || step !== "idle") return;
    if (recoveryAttemptedRef.current || purchaseInFlight.current) return;
    const pending = loadPendingPurchase();
    if (!pending || pending.signalId !== signalId.toString() || pending.buyer !== address) return;
    recoveryAttemptedRef.current = true;

    runDecryptionRecovery();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signalId, isConnected, address, signal]);

  /** Has the buyer already paid on-chain but not yet decrypted? Used to
   * decide whether to show a "Retry decryption" button. Truthy when a
   * pending-purchase state exists for this signal + buyer. */
  const hasPendingDecryption = (() => {
    if (!signalId || !address) return false;
    const pending = loadPendingPurchase();
    return !!(
      pending &&
      pending.signalId === signalId.toString() &&
      pending.buyer === address
    );
  })();

  if (!isConnected) {
    return (
      <div className="text-center py-20">
        <h1 className="text-3xl font-bold text-slate-900 mb-4">
          Purchase Signal
        </h1>
        <p className="text-slate-500">
          Connect your wallet to purchase this signal.
        </p>
      </div>
    );
  }

  if (signalLoading) {
    return (
      <div className="text-center py-20">
        <p className="text-slate-500">Loading signal data...</p>
      </div>
    );
  }

  if (signalError) {
    return (
      <div className="text-center py-20">
        <h1 className="text-3xl font-bold text-slate-900 mb-4">
          Signal Not Found
        </h1>
        <p className="text-slate-500 mb-8">{signalError}</p>
        <button onClick={() => router.push("/idiot")} className="btn-primary">
          Back to Dashboard
        </button>
      </div>
    );
  }

  if (!signal) {
    return (
      <div className="text-center py-20">
        <p className="text-slate-500">Signal not found</p>
      </div>
    );
  }

  const expiresDate = new Date(Number(signal.expiresAt) * 1000);
  const isExpired = expiresDate < new Date();
  const isActive = signal.status === SignalStatus.Active && !isExpired;

  const handlePurchase = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!signalId) return;
    if (purchaseInFlight.current) return;
    purchaseInFlight.current = true;

    const buyerAddress = address;
    if (!buyerAddress) {
      setStepError("Wallet not connected. Please connect your wallet and try again.");
      setStep("idle");
      purchaseInFlight.current = false;
      return;
    }

    const pauseErr = checkPause("escrow", "Purchase");
    if (pauseErr) {
      setStepError(pauseErr);
      setStep("idle");
      purchaseInFlight.current = false;
      return;
    }

    // If a purchase is already on-chain (retry after partial share collection),
    // skip directly to share collection instead of re-sending the on-chain tx.
    const pending = loadPendingPurchase();
    if (pending && pending.signalId === signalId.toString() && pending.buyer === buyerAddress) {
      setStepError(null);
      try {
        setStep("recovering");
        const validators = await discoverValidatorClients();
        // v1723: load cached buyer signature; sign fresh if missing so the
        // pending-purchase resume path passes the validator's mandatory
        // buyer_signature gate.
        let buyerSig = "";
        const sigCacheKey = `djinn:buyerSig:${buyerAddress.toLowerCase()}:${signalId}`;
        try {
          const cached = sessionStorage.getItem(sigCacheKey);
          if (cached) buyerSig = cached;
        } catch {}
        if (!buyerSig && walletClient) {
          try {
            buyerSig = await walletClient.signMessage({
              message: `djinn:purchase:${signalId}`,
            });
            try { sessionStorage.setItem(sigCacheKey, buyerSig); } catch {}
          } catch {
            // signing rejected — proceed with empty sig
          }
        }
        const purchaseReq = {
          buyer_address: buyerAddress,
          sportsbook: "",
          available_indices: [] as number[],
          buyer_signature: buyerSig,
        };

        // Query threshold: try to get it from the first validator's purchase response
        let threshold = 3; // default (most signals use 2 or 3)

        const shares: ShamirShare[] = [];
        for (let attempt = 0; attempt < 4 && shares.length < threshold; attempt++) {
          if (attempt > 0) await new Promise((r) => setTimeout(r, 3000));
          const results = await Promise.allSettled(
            validators.map((v) =>
              Promise.race([
                v.purchaseSignal(signalId.toString(), purchaseReq),
                new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), 15000)),
              ]),
            ),
          );
          for (const result of results) {
            if (result.status === "fulfilled" && result.value?.available && result.value.encrypted_key_share && result.value.share_x != null) {
              const x = result.value.share_x;
              if (!shares.some((s) => s.x === x)) {
                shares.push({ x, y: BigInt("0x" + result.value.encrypted_key_share) });
              }
            }
          }
          console.log(`[retry] attempt ${attempt + 1}: ${shares.length}/${threshold} shares`);
        }

        if (shares.length >= threshold) {
          setStep("decrypting");
          try {
            const reconstructedBigInt = reconstructSecret(shares);
            const keyBytes = bigIntToKey(reconstructedBigInt);
            const blobBytes = signal.encryptedBlob.startsWith("0x") ? signal.encryptedBlob.slice(2) : signal.encryptedBlob;
            const blobStr = new TextDecoder().decode(fromHex(blobBytes));
            const colonIdx = blobStr.indexOf(":");
            if (colonIdx === -1) throw new Error("Invalid encrypted blob format");
            const plaintext = await decrypt(blobStr.slice(colonIdx + 1), blobStr.slice(0, colonIdx), keyBytes);
            const parsed = JSON.parse(plaintext);
            setDecryptedPick(parsed);
            clearPendingPurchase();
          } catch (decErr) {
            setStepError(`Decryption failed: ${decErr instanceof Error ? decErr.message : String(decErr)}`);
          }
        } else {
          setStepError(`Collected ${shares.length} of ${threshold} shares. Some validators may be slow. Try again in a moment.`);
        }
        setStep("idle");
      } catch (err) {
        setStepError(`Recovery failed: ${err instanceof Error ? err.message : String(err)}`);
        setStep("idle");
      }
      purchaseInFlight.current = false;
      return;
    }

    setStepError(null);

    // Validate notional early so we don't waste MPC computation on bad input
    const notionalNum = parseFloat(notional);
    if (isNaN(notionalNum) || !Number.isFinite(notionalNum) || notionalNum <= 0) {
      setStepError("Invalid notional");
      return;
    }
    if (notionalNum < 1) {
      setStepError("Minimum notional is $1.00");
      return;
    }

    try {
      const t0 = performance.now();

      // v2 signals: lines are off-chain, skip client-side line check entirely
      // Validators handle availability verification through MPC
      const signalIsV2 = signal.linesHash && signal.linesHash !== "0x" + "0".repeat(64);

      let checkResult: CheckResponse | null = null;
      let bestOdds = 1.91; // fallback
      // Phase 1 MPC batch settlement vectors: populated from check-odds
      // when on a v2 signal so we can commit them to the validator
      // purchase ledger. Null-safe: old signals / failed check-odds
      // leave these undefined and the validator stores nothing.
      let perLineBpas: number[] | undefined = undefined;
      let perLineWpas: number[] | undefined = undefined;

      if (!signalIsV2) {
        // Step 1: Check line availability via miner network (subnet only)
        setStep("checking_lines");

        const candidateLines: CandidateLine[] = signal.decoyLines.map(
          (raw, i) =>
            decoyLineToCandidateLine(
              raw,
              i + 1,
              signal.sport,
              idStr ?? "",
            ),
        );

        // Resilient check: races platform Odds API against miner network.
        // Platform API wins in ~100ms; miners are slower but provide redundancy.
        console.log("[purchase] starting line check for signal", idStr, "with", candidateLines.length, "lines");
        let checkError: string | null = null;
        try {
          const result = await checkLinesViaSubnet({ lines: candidateLines });
          console.log("[purchase] line check complete:", result.available_indices.length, "of", candidateLines.length, "available");
          if (result.available_indices.length > 0) {
            checkResult = result;
          } else {
            // Extract reasons why lines are unavailable for better error messaging
            const reasons = result.results
              .map((r) => (r as unknown as Record<string, unknown>).unavailable_reason as string | undefined)
              .filter(Boolean);
            const uniqueReasons = [...new Set(reasons)];
            if (result.api_error) {
              checkError = "Could not reach any odds data provider. Please try again in a minute.";
            } else if (uniqueReasons.includes("game_started")) {
              checkError = "This game appears to have started or been removed from the odds feed.";
            } else if (uniqueReasons.includes("line_moved")) {
              checkError = "The line has moved since this signal was created. The exact line is no longer available at any sportsbook.";
            } else if (uniqueReasons.includes("market_unavailable")) {
              checkError = "This market is temporarily unavailable at all sportsbooks. Try again shortly.";
            } else if (uniqueReasons.includes("no_data")) {
              checkError = "No odds data available for this event. The odds provider may be temporarily down.";
            }
          }
        } catch (e) {
          console.log("[purchase] line check FAILED:", String(e).slice(0, 200));
          checkError = "Could not reach any odds data provider. Please try again in a minute.";
        }

        if (!checkResult || checkResult.available_indices.length === 0) {
          console.log("[purchase] ABORT: no lines available, reason:", checkError);
          setStepError(
            checkError || "No lines are currently available at any sportsbook. The signal may have gone stale. Check back later.",
          );
          setStep("idle");
          return;
        }

        console.log("[purchase] available_indices:", checkResult.available_indices,
          "total_lines:", candidateLines.length,
          "source:", (checkResult as unknown as Record<string, unknown>).source || "miner",
          "unavailable:", checkResult.results.filter(r => !r.available).map(r =>
            `${r.index}:${(r as unknown as Record<string, unknown>).unavailable_reason ?? "unknown"}`
          ),
          "available:", checkResult.results.filter(r => r.available).map(r =>
            `${r.index}:${r.bookmakers.length}books`
          ));

        // Extract best odds across all bookmakers for any available line
        for (const lineResult of checkResult.results) {
          if (lineResult.available && lineResult.bookmakers) {
            for (const bm of lineResult.bookmakers) {
              if (bm.odds > bestOdds) {
                bestOdds = bm.odds;
              }
            }
          }
        }
      } else {
        // v2 signal: fetch live odds through validator's check-odds endpoint
        setStep("checking_lines");
        console.log("[purchase] v2 signal, fetching odds through validator");
        try {
          const validators = await discoverValidatorClients();
          const savedBooks = localStorage.getItem(`djinn:books:${buyerAddress.toLowerCase()}`);
          // Default to all books when the buyer hasn't explicitly configured
          // preferences, matching useBookPreferences(). Defaulting to a
          // subset silently excluded lines and made purchases fail.
          const buyerBooks: string[] = savedBooks ? JSON.parse(savedBooks) : [...ALL_BOOK_KEYS];

          // Quorum-aware check-odds: under DJINN_FF_QUORUM_STRICT, require
          // at least 3 validators to agree on the executable line set
          // before quoting odds to the buyer. This prevents a single
          // misbehaving validator from dictating the price. With the flag
          // OFF (default on main) we keep first-responder semantics for
          // backwards compatibility and latency.
          type CheckOddsLine = {
            index: number;
            executable: boolean;
            bpa?: number;
            wpa?: number;
            per_book?: { bookmaker: string; odds: number }[];
          };
          type CheckOddsResp = { odds?: CheckOddsLine[]; bpa_mode?: boolean };
          const oddsCalls: Promise<CheckOddsResp>[] = validators.map(async (v) => {
            const resp = await fetch(`${v.baseUrl}/v1/signal/${signalId}/check-odds`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                buyer_address: buyerAddress,
                buyer_books: buyerBooks,
              }),
              signal: AbortSignal.timeout(15_000),
            });
            if (!resp.ok) throw new Error(`${resp.status}`);
            return resp.json() as Promise<CheckOddsResp>;
          });
          const quorumStrict = isQuorumStrictFor("checkOdds");
          const oddsQuorum = await callWithQuorumOrFirst<CheckOddsResp>(oddsCalls, {
            strict: quorumStrict,
            quorum: 3,
            bucketBy: (r) => {
              const exec = (r.odds || [])
                .filter((o) => o.executable)
                .map((o) => o.index)
                .sort((a, b) => a - b)
                .join(",");
              return `exec:${exec}`;
            },
          });
          if (quorumStrict && oddsQuorum.verdict !== "quorum_reached") {
            console.warn("[purchase] check-odds quorum failed", {
              verdict: oddsQuorum.verdict,
              total: oddsQuorum.total,
              successCount: oddsQuorum.allSuccess.length,
              errorCount: oddsQuorum.errorCount,
            });
            throw new Error(
              `check-odds quorum_failed: ${oddsQuorum.verdict} (` +
              `${oddsQuorum.allSuccess.length}/${oddsQuorum.total} responded, ` +
              `none agreed)`,
            );
          }
          const oddsResult = oddsQuorum.result;
          if (!oddsResult) {
            throw new Error("check-odds: no validator response");
          }

          const executableIndices = (oddsResult.odds || [])
            .filter((o: { executable: boolean }) => o.executable)
            .map((o: { index: number }) => o.index);

          // Defensive: a single validator returning "no lines executable"
          // could be lying (censorship attack on a specific buyer/signal)
          // or just behind on miner data. Don't surface "no lines available"
          // to the buyer until we've heard from at least one more validator
          // and they agree. If even one other validator sees executable
          // lines, fall through to the wider response.
          //
          // The strict-quorum path already protects against single-validator
          // disagreement when DJINN_FF_QUORUM_STRICT is on. This guard adds
          // a second-opinion check for the default (race) mode, so a censoring
          // validator can't deny purchases by being fastest.
          if (executableIndices.length === 0 && !quorumStrict && oddsQuorum.allSuccess.length < 2) {
            console.warn("[purchase] first responder reported zero executable lines; waiting for confirmation");
            try {
              const allResponses = await Promise.allSettled(oddsCalls);
              const corroborating = allResponses
                .filter((r): r is PromiseFulfilledResult<CheckOddsResp> => r.status === "fulfilled")
                .map((r) => r.value)
                .filter((r) => (r.odds || []).some((o) => o.executable));
              if (corroborating.length > 0) {
                console.log(`[purchase] ${corroborating.length} other validator(s) saw executable lines, using their view`);
                const second = corroborating[0];
                const secondExec = (second.odds || [])
                  .filter((o) => o.executable)
                  .map((o) => o.index);
                if (secondExec.length > 0) {
                  // Use the corroborating response in place of the first one
                  const corroborated = second;
                  const corroboratedExec = secondExec;
                  checkResult = {
                    results: (corroborated.odds || []).map((o: CheckOddsLine) => ({
                      index: o.index,
                      available: o.executable,
                      bookmakers: o.executable ? (o.per_book ?? []) : [],
                    })),
                    available_indices: corroboratedExec,
                    response_time_ms: 0,
                  };
                  perLineBpas = (corroborated.odds || []).map(
                    (o: CheckOddsLine) => Math.round((o.bpa ?? 0) * 1_000_000),
                  );
                  perLineWpas = (corroborated.odds || []).map(
                    (o: CheckOddsLine) => Math.round((o.wpa ?? 0) * 1_000_000),
                  );
                  for (const o of corroborated.odds || []) {
                    const bpa = o.bpa ?? 0;
                    if (o.executable && bpa > bestOdds) bestOdds = bpa;
                  }
                  // Successfully corroborated, skip the "no lines" branch
                  if (checkResult) {
                    checkResultRef.current = checkResult;
                    setAvailableIndices(checkResult.available_indices);
                  }
                  setMarketOdds(bestOdds);
                  setStep("purchasing_validator");
                  // Fall through to the post-check-odds purchase path
                  // by continuing past the "no lines" branch below.
                }
              }
            } catch (corroborateErr) {
              console.warn("[purchase] corroboration check failed:", corroborateErr);
            }
          }

          if (executableIndices.length > 0 && !checkResult) {
            checkResult = {
              results: (oddsResult.odds || []).map((o: CheckOddsLine) => ({
                index: o.index,
                available: o.executable,
                bookmakers: o.executable ? (o.per_book ?? []) : [],
              })),
              available_indices: executableIndices,
              response_time_ms: 0,
            };

            // MPC batch settlement Phase 1: capture per-line BPA/WPA
            // vectors (scaled to ODDS_PRECISION = 1e6 integer units)
            // so we can pass them to the validator for commit. This
            // is what will eventually drive correct per-buyer
            // settlement via MPC polynomial eval at the secret real
            // index — see docs/specs/mpc-batch-settlement.md.
            perLineBpas = (oddsResult.odds || []).map(
              (o: { bpa?: number }) =>
                Math.round((o.bpa ?? 0) * 1_000_000),
            );
            perLineWpas = (oddsResult.odds || []).map(
              (o: { wpa?: number }) =>
                Math.round((o.wpa ?? 0) * 1_000_000),
            );

            for (const o of oddsResult.odds || []) {
              const bpa = o.bpa ?? 0;
              if (o.executable && bpa > bestOdds) bestOdds = bpa;
            }
          } else if (!checkResult) {
            // Reached only when neither the first responder nor any
            // corroborating validator saw executable lines. Treat as
            // genuinely unavailable.
            setStepError("No lines currently executable at your sportsbooks. The game may have started or lines have moved.");
            setStep("idle");
            purchaseInFlight.current = false;
            return;
          }
        } catch (e) {
          console.error("[purchase] v2 odds check failed:", e);
          setStepError("Could not verify lines with validators. Please try again.");
          setStep("idle");
          purchaseInFlight.current = false;
          return;
        }
      }

      // Store check results for post-purchase bookmaker lookup
      if (checkResult) {
        checkResultRef.current = checkResult;
        setAvailableIndices(checkResult.available_indices);
      }
      setMarketOdds(bestOdds);

      // Step 2: Verify availability with validators (MPC check -- before payment)
      console.log(`[purchase] Step 1 (line check) took ${((performance.now() - t0) / 1000).toFixed(1)}s`);
      setStep("purchasing_validator");

      const validators = await discoverValidatorClients();

      // Sign a purchase message to prove buyer_address ownership.
      //
      // Cached per (buyer, signalId) in sessionStorage so that a retried
      // purchase attempt after a transient failure does NOT re-prompt
      // the wallet. Purchase messages are deterministic (just the
      // signalId), so the cached signature is always valid for the
      // same signal from the same buyer.
      let buyerSig = "";
      const sigCacheKey = `djinn:buyerSig:${buyerAddress?.toLowerCase() ?? ""}:${signalId}`;
      try {
        const cached = sessionStorage.getItem(sigCacheKey);
        if (cached) buyerSig = cached;
      } catch {
        // sessionStorage unavailable (SSR, private browsing quirks) — fall through
      }
      if (!buyerSig && walletClient) {
        try {
          buyerSig = await walletClient.signMessage({
            message: `djinn:purchase:${signalId}`,
          });
          try {
            sessionStorage.setItem(sigCacheKey, buyerSig);
          } catch {
            // Cache write failure is non-fatal
          }
        } catch {
          // Non-fatal: validator accepts unsigned in dev mode
        }
      }

      // Query actual Shamir threshold from validators (don't hardcode).
      // Race all validators, take the first response.
      let shamirThreshold = 2; // bootstrap default (SHAMIR_MIN=2)
      try {
        const thresholdResult = await Promise.any(
          validators.map((v) =>
            v.shareInfo(signalId.toString()).then((r) => r.shamir_threshold),
          ),
        );
        if (thresholdResult >= 2 && thresholdResult <= 7) {
          shamirThreshold = thresholdResult;
        }
      } catch {
        console.warn("[purchase] Could not query shamir threshold, using default:", shamirThreshold);
      }
      console.log("[purchase] shamir_threshold:", shamirThreshold);

      const purchaseReq = {
        buyer_address: buyerAddress,
        sportsbook: "",
        available_indices: checkResult ? checkResult.available_indices : [],
        buyer_signature: buyerSig,
        // MPC batch settlement Phase 1: send the per-line BPA/WPA
        // vectors so the validator can record them keyed by
        // (signalId, buyer). Old validators ignore these fields;
        // new validators store them for future audit settlement.
        bpas: perLineBpas,
        wpas: perLineWpas,
        bpa_mode: perLineBpas ? signal.bpaMode : undefined,
      };

      const MPC_TIMEOUT_MS = 45_000;

      // Query all validators in parallel with a two-phase strategy:
      //  1. Race for the first positive response (Promise.any on a filtered
      //     predicate). As soon as ANY validator says "available" or
      //     "payment_required", we can proceed immediately — no need to wait
      //     for slow or broken peers. This preserves the fast-path latency
      //     we had before.
      //  2. If the race rejects (everyone returned not-available OR errored),
      //     fall back to Promise.allSettled to materialize every real response
      //     so we can build a precise friendly error message.
      type MpcResponse = Awaited<ReturnType<typeof validators[0]["purchaseSignal"]>>;

      const wrappedCalls = validators.map((v) =>
        Promise.race([
          v.purchaseSignal(signalId.toString(), purchaseReq),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error("MPC timeout")), MPC_TIMEOUT_MS),
          ),
        ]),
      );

      // Track every settled result for the error-path diagnostics without
      // double-awaiting the same promises. Each slot is filled in-place as
      // the underlying promise settles.
      const availabilityResults: PromiseSettledResult<MpcResponse>[] = validators.map(
        () => ({ status: "rejected" as const, reason: new Error("pending") }),
      );
      wrappedCalls.forEach((p, i) => {
        p.then(
          (value) => {
            availabilityResults[i] = { status: "fulfilled", value };
          },
          (reason) => {
            availabilityResults[i] = { status: "rejected", reason };
          },
        );
      });

      // Fast path: resolve as soon as any validator confirms availability.
      let firstAvailable: MpcResponse | null = null;
      try {
        firstAvailable = await Promise.any(
          wrappedCalls.map((p) =>
            p.then((r) => {
              if (
                r.available ||
                (r as unknown as Record<string, string>).status === "payment_required"
              ) {
                return r;
              }
              throw new Error(`unavailable:${r.status}`);
            }),
          ),
        );
      } catch {
        // Every validator either rejected or responded unavailable. Fall
        // through: wait for all remaining pending responses so the
        // diagnostics below see the full picture.
        await Promise.allSettled(wrappedCalls);
      }

      // Fast path already settled this: if firstAvailable is non-null, at
      // least one validator confirmed availability (or payment_required,
      // which we treat as positive — share release is gated on on-chain
      // payment instead of the MPC bit).
      const anyAvailable = firstAvailable !== null;

      // Log MPC results from each validator for debugging
      console.log("[purchase] MPC results:", availabilityResults.map((r, i) => {
        if (r.status === "fulfilled") {
          const v = r.value;
          const reason = (v as unknown as Record<string, unknown>).mpc_failure_reason || "";
          const parts = (v as unknown as Record<string, unknown>).mpc_participants || "";
          return `v${i}:${v.available ? "AVAIL" : "UNAVAIL"} (${v.status}/${v.message}) participants=${parts} reason=${reason}`;
        }
        return `v${i}:REJECTED (${r.reason?.message?.slice(0, 80) || "unknown"})`;
      }));

      if (!anyAvailable) {
        const errors = availabilityResults
          .filter((r): r is PromiseRejectedResult => r.status === "rejected")
          .map((r) => r.reason?.message || "unknown");
        const unavailableResponses = availabilityResults
          .filter((r) => r.status === "fulfilled" && !r.value.available)
          .map((r) => (r as PromiseFulfilledResult<MpcResponse>).value);
        const mpcReasons = unavailableResponses
          .map((v) => (v as unknown as Record<string, unknown>).mpc_failure_reason as string | undefined)
          .filter(Boolean) as string[];

        const fulfilledCount = availabilityResults.filter((r) => r.status === "fulfilled").length;
        const rejectedCount = availabilityResults.filter((r) => r.status === "rejected").length;
        const allNotFound = errors.length > 0 && errors.every((e) => e.includes("not found"));
        const insufficientPeers = mpcReasons.some((r) => r.includes("insufficient") || r.includes("init_failed") || r.includes("gate_"));
        const noAvailableIndices = mpcReasons.some((r) => r.includes("no_available_indices"));
        // Only attribute failure to "line mismatch at sportsbook" when the
        // validators EXPLICITLY signalled a successful MPC with a negative
        // result. Current validators set mpc_participants >= threshold and
        // mpc_failure_reason == null in that specific case. Anything else
        // (no participants field, missing, or a failure_reason we didn't
        // match above) is treated as a generic protocol failure to avoid
        // misleading the user with a sportsbook-line explanation for what
        // is really a backend issue.
        const confirmedLineMismatch = unavailableResponses.some((v) => {
          const rec = v as unknown as Record<string, unknown>;
          const participants = rec.mpc_participants;
          const reason = rec.mpc_failure_reason;
          return (
            typeof participants === "number" &&
            participants >= 2 &&
            (reason === null || reason === undefined || reason === "")
          );
        });
        const executableCount = checkResult?.available_indices.length ?? 0;
        const totalLines = signal.lineCount || checkResult?.results.length || 0;

        let friendlyMsg: string;
        if (allNotFound) {
          friendlyMsg = "We couldn't find this signal on any active validator. It may have been created during a network reset. Nothing was charged — try a different signal.";
        } else if (confirmedLineMismatch && !insufficientPeers && !noAvailableIndices) {
          // Validators ran MPC to completion with enough participants AND
          // explicitly reported no failure reason — the only way to reach
          // this branch is a negative MPC result: the genius's pick is not
          // in the buyer's current executable set.
          if (executableCount > 0 && totalLines > 0 && executableCount < totalLines) {
            friendlyMsg = `This signal's pick isn't among the ${executableCount} of ${totalLines} lines your sportsbook is currently offering. Nothing was charged. This usually means the line has moved or the book pulled it. Retrying only helps if it was a temporary suspension — otherwise this signal isn't executable for you.`;
          } else {
            friendlyMsg = "This signal's pick isn't currently executable at your sportsbook. Nothing was charged. The line has likely moved or been pulled. Retrying only helps if it was a temporary suspension.";
          }
        } else if (insufficientPeers) {
          friendlyMsg = "Not enough validators are online to verify this signal right now. Nothing was charged. Please try again in a few minutes.";
        } else if (noAvailableIndices) {
          friendlyMsg = "No sportsbook lines are currently executable for this signal. Nothing was charged. Please try again shortly.";
        } else {
          const allTimedOut = errors.length > 0 && errors.every((e) => e.toLowerCase().includes("timeout") || e.toLowerCase().includes("timed out") || e.includes("502") || e.includes("504"));
          const allNetworkErrors = errors.length > 0 && errors.every((e) => e.includes("502") || e.includes("503") || e.includes("504") || e.includes("fetch") || e.toLowerCase().includes("network"));
          if (allTimedOut) {
            friendlyMsg = "The validator network is slow right now and the check timed out. Nothing was charged. Please try again in a minute.";
          } else if (allNetworkErrors) {
            friendlyMsg = "We couldn't reach any validators. The network may be having a rough moment. Nothing was charged. Please try again shortly.";
          } else if (fulfilledCount === 0 && rejectedCount > 0) {
            friendlyMsg = `The validators couldn't complete the check (${errors[0]?.slice(0, 120) || "unknown error"}). Nothing was charged. Please try again.`;
          } else {
            friendlyMsg = "We couldn't verify this signal right now. Nothing was charged. Please try again in a minute.";
          }
        }
        console.log("[purchase] MPC failure reasons:", mpcReasons, "rejected errors:", errors, "unavailable responses:", unavailableResponses.length, "fulfilled:", fulfilledCount, "rejected:", rejectedCount);
        setStepError(friendlyMsg);
        setStep("idle");
        return;
      }

      // Collect any shares already released (dev mode without chain_client)
      const collectedShares: ShamirShare[] = [];
      for (const result of availabilityResults) {
        if (
          result.status === "fulfilled" &&
          result.value.available &&
          result.value.encrypted_key_share &&
          result.value.share_x != null
        ) {
          collectedShares.push({
            x: result.value.share_x,
            y: BigInt("0x" + result.value.encrypted_key_share),
          });
        }
      }

      // Step 3: Execute on-chain purchase (now that MPC confirmed availability)
      console.log(`[purchase] Step 2 (MPC) took ${((performance.now() - t0) / 1000).toFixed(1)}s total`);
      setStep("purchasing_chain");

      // notionalNum already validated at the top of handlePurchase
      if (!bestOdds || bestOdds < 1.01) {
        setStepError("Could not determine market odds. Try again.");
        setStep("idle");
        return;
      }

      const notionalBig = BigInt(Math.floor(notionalNum * 1_000_000));
      // Contract uses 6-decimal precision (ODDS_PRECISION = 1e6)
      const oddsBig = BigInt(Math.floor(bestOdds * 1_000_000));

      // Fee = notional * maxPriceBps / 10_000
      const feeBig = (notionalBig * BigInt(signal.maxPriceBps)) / 10_000n;
      // Read balance fresh from chain (the React state may be stale if the
      // user deposited after the page rendered but before clicking Purchase).
      let freshBalance = escrowBalance ?? 0n;
      if (buyerAddress) {
        try {
          const bal = await getEscrowContract(getReadProvider()).getBalance(buyerAddress);
          freshBalance = BigInt(bal);
        } catch {
          // Fall back to React state
        }
      }
      if (freshBalance < feeBig) {
        const needed = Number(feeBig) / 1e6;
        const have = Number(freshBalance) / 1e6;
        const fmtNeeded = needed > 0 && needed < 0.01 ? "< $0.01" : `$${needed.toFixed(2)}`;
        const fmtHave = `$${have.toFixed(2)}`;
        setStepError(
          `Insufficient escrow balance: you have ${fmtHave} but need ${fmtNeeded}. Use the deposit form above.`,
        );
        setStep("idle");
        return;
      }

      await purchase(signalId, notionalBig, oddsBig);

      // Persist state so we can recover if user refreshes after payment
      savePendingPurchase(signalId.toString(), buyerAddress);

      console.log(`[purchase] Step 3 (on-chain tx) took ${((performance.now() - t0) / 1000).toFixed(1)}s total`);
      // Step 4: Collect key shares from validators (payment now exists
      // on-chain). Need at least shamirThreshold shares for reconstruction.
      const NEEDED_SHARES = shamirThreshold;
      // Fill the remainder via the shared retry helper. Keeps the main
      // purchase flow and the on-mount recovery on the same code path,
      // with the same retry/backoff behavior, the same threshold
      // detection, and the same error shape. The helper is idempotent
      // on the validator side — re-querying purchaseSignal after
      // on-chain payment is safe.
      if (collectedShares.length < NEEDED_SHARES) {
        setStep("collecting_shares");
        const { shares: retriedShares } = await collectSharesWithRetry(
          validators,
          signalId.toString(),
          purchaseReq,
          {
            existingShares: collectedShares,
            onProgress: (got, need, attempt) => {
              console.log(
                `[purchase] share collection attempt ${attempt + 1}: ${got}/${need} shares`,
              );
            },
          },
        );
        // collectSharesWithRetry returns a new array; replace our local
        // list with its contents so reconstruction uses the full set.
        collectedShares.length = 0;
        collectedShares.push(...retriedShares);
      }

      // Step 5: Decrypt the signal
      console.log(`[purchase] Step 4 (share collection) took ${((performance.now() - t0) / 1000).toFixed(1)}s total, got ${collectedShares.length} shares (need ${NEEDED_SHARES})`);
      setStep("decrypting");

      if (collectedShares.length < NEEDED_SHARES) {
        setStepError(
          `Couldn't collect enough decryption keys (${collectedShares.length}/${NEEDED_SHARES}). ` +
          "Your purchase is safe on-chain — nothing was double-charged. " +
          "Click \"Retry decryption\" below to try again, or come back in a minute.",
        );
        setStep("idle");
        purchaseInFlight.current = false;
        return;
      }

      if (collectedShares.length > 0) {
        try {
          // Reconstruct AES key from Shamir shares (need ≥ threshold shares)
          const reconstructedBigInt = reconstructSecret(collectedShares);
          const keyBytes = bigIntToKey(reconstructedBigInt);

          // The encrypted blob is stored on-chain as hex-encoded bytes
          // Parse it: format is "iv:ciphertext"
          const blobBytes = signal.encryptedBlob.startsWith("0x")
            ? signal.encryptedBlob.slice(2)
            : signal.encryptedBlob;
          const blobStr = new TextDecoder().decode(fromHex(blobBytes));
          const colonIdx = blobStr.indexOf(":");

          if (colonIdx === -1) {
            throw new Error("Invalid encrypted blob format (missing iv:ciphertext separator)");
          }

          const iv = blobStr.slice(0, colonIdx);
          const ciphertext = blobStr.slice(colonIdx + 1);

          if (!iv || !ciphertext) {
            throw new Error("Invalid encrypted blob format (empty iv or ciphertext)");
          }

          const plaintext = await decrypt(ciphertext, iv, keyBytes);
          let parsed: { realIndex: number; pick: string };
          try {
            parsed = JSON.parse(plaintext);
          } catch {
            throw new Error("Decrypted data is not valid JSON. Key may be incorrect.");
          }
          if (typeof parsed.realIndex !== "number" || typeof parsed.pick !== "string") {
            throw new Error("Decrypted data missing required fields (realIndex, pick)");
          }
          const maxLineCount = signal.lineCount > 0 ? signal.lineCount : signal.decoyLines.length;
          if (parsed.realIndex < 1 || (maxLineCount > 0 && parsed.realIndex > maxLineCount)) {
            throw new Error(`Invalid realIndex ${parsed.realIndex} (expected 1-${maxLineCount})`);
          }
          setDecryptedPick(parsed);

          // Find best bookmaker for the real pick from miner check results
          const storedCheck = checkResultRef.current;
          if (storedCheck) {
            const realLineResult = storedCheck.results.find(
              (r) => r.index === parsed.realIndex,
            );
            if (realLineResult?.bookmakers?.length) {
              const sorted = [...realLineResult.bookmakers].sort(
                (a, b) => b.odds - a.odds,
              );
              setBestBookmaker(sorted[0]);
              setRealLineBooks(sorted);
            }
          }

          // Persist purchased signal data for recovery
          if (buyerAddress) {
            const bestBook = checkResultRef.current?.results
              .find((r) => r.index === parsed.realIndex)
              ?.bookmakers?.sort((a, b) => b.odds - a.odds)?.[0];
            savePurchasedSignal(buyerAddress, {
              signalId: signalId.toString(),
              realIndex: parsed.realIndex,
              pick: parsed.pick,
              sportsbook: bestBook?.bookmaker ?? "",
              notional: notional,
              purchasedAt: Math.floor(Date.now() / 1000),
            });

            // Store recovery blob on-chain (non-blocking — localStorage is primary).
            // Debounced: skips the on-chain write + wallet popup if one already
            // happened for this wallet within the last 2 minutes (rapid-purchase
            // bursts get one store at the start, not one per purchase).
            if (walletClient) {
              import("@/lib/contracts").then(({ ADDRESSES }) => {
                if (ADDRESSES.keyRecovery === "0x0000000000000000000000000000000000000000") return;
                Promise.all([
                  import("@wagmi/core"),
                  import("@/app/providers"),
                  import("@/lib/recovery"),
                  import("@/lib/preferences"),
                  import("@/lib/hooks/useSettledSignals"),
                ]).then(([{ waitForTransactionReceipt }, { wagmiConfig }, { maybeStoreRecovery }, { getPurchasedSignals }, { getSavedSignals }]) => {
                  maybeStoreRecovery(
                    buyerAddress,
                    (params) => walletClient.signTypedData(params),
                    walletClient,
                    getSavedSignals(buyerAddress),
                    async (h) => { await waitForTransactionReceipt(wagmiConfig, { hash: h }); },
                    getPurchasedSignals(buyerAddress),
                  ).catch((err: unknown) => {
                    console.warn("[recovery] Failed to store idiot recovery blob:", err);
                  });
                });
              });
            }
          }
        } catch (decryptErr) {
          console.warn("Decryption error:", decryptErr);
          setStepError(
            "Your signal was purchased successfully, but the encryption key is still being reconstructed. The real pick will appear once enough key shares arrive (usually within seconds). Refresh the page to check.",
          );
        }
      }

      clearPendingPurchase();
      setStep("complete");
      triggerOnboardingRefresh();
    } catch (err) {
      setStepError(err instanceof Error ? err.message : "Purchase failed");
      setStep("idle");
    } finally {
      purchaseInFlight.current = false;
    }
  };

  if (step === "complete") {
    return (
      <div className="max-w-2xl mx-auto text-center py-12 sm:py-20">
        <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-6">
          <svg
            className="w-8 h-8 text-green-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 mb-4">
          Signal Purchased & Decrypted
        </h1>

        {decryptedPick ? (
          <div className="card text-left mb-8">
            <div className="rounded-lg bg-green-50 border border-green-200 p-4 mb-4">
              <p className="text-xs text-green-600 uppercase tracking-wide mb-1">
                Real Pick (Line #{decryptedPick.realIndex})
              </p>
              <p className="text-lg font-bold text-green-800">
                {decryptedPick.pick}
              </p>
              {(() => {
                // Odds display honoring the sport's conventional format.
                // Two separate numbers matter to the buyer:
                //  1. Committed odds: what the genius promised at signal
                //     creation time. This is the price the buyer is
                //     guaranteed to be able to get, or the purchase should
                //     void.
                //  2. Current market: the live best price at the buyer's
                //     books right now, from the most recent check-odds
                //     response.
                // When they differ, show both. When only one is known,
                // show whichever we have. Never call a worse-than-committed
                // price "best" — that was the bug that started this task.
                const primaryIsDecimal = usesDecimalOdds(signal.sport);
                const fmt = (dec: number) => {
                  const primary = formatOdds(
                    dec,
                    primaryIsDecimal ? "decimal" : "american",
                  );
                  const secondary = formatOdds(
                    dec,
                    primaryIsDecimal ? "american" : "decimal",
                  );
                  return `${primary} (${secondary})`;
                };

                const committed = decryptedPick?.minOdds;
                const current = bestBookmaker?.odds;

                if (committed == null && current == null) {
                  return null;
                }

                // When we have both, render a two-line comparison with a
                // movement indicator.
                if (committed != null && current != null) {
                  const moved = current < committed;
                  const movedUp = current > committed;
                  const bookName = bestBookmaker?.bookmaker || "market";
                  return (
                    <div className="text-sm text-green-700 mt-2 space-y-1">
                      <p>
                        Committed: {fmt(committed)}
                      </p>
                      <p>
                        Current best: {fmt(current)} at {bookName}
                        {moved && (
                          <span className="ml-2 inline-flex items-center rounded-full bg-amber-100 border border-amber-300 px-2 py-0.5 text-[10px] font-semibold text-amber-700 uppercase tracking-wide">
                            line moved
                          </span>
                        )}
                        {movedUp && (
                          <span className="ml-2 inline-flex items-center rounded-full bg-green-100 border border-green-300 px-2 py-0.5 text-[10px] font-semibold text-green-700 uppercase tracking-wide">
                            improved
                          </span>
                        )}
                      </p>
                    </div>
                  );
                }

                // Only one is known: label it honestly.
                if (committed != null) {
                  return (
                    <p className="text-sm text-green-700 mt-2">
                      Committed: {fmt(committed)}
                    </p>
                  );
                }
                return (
                  <p className="text-sm text-green-700 mt-2">
                    Current best: {fmt(current!)} at {bestBookmaker!.bookmaker}
                  </p>
                );
              })()}
              <details className="text-xs text-green-700 mt-3">
                <summary className="cursor-pointer select-none hover:underline">
                  What do these odds mean for me? (payoff math)
                </summary>
                <div className="mt-2 space-y-1.5 text-green-800 max-w-prose">
                  {(() => {
                    const committedDecimal = decryptedPick?.minOdds ?? null;
                    const slaPct = Number(signal.slaMultiplierBps) / 100;
                    const committedPct = committedDecimal != null ? ((committedDecimal - 1) * 100).toFixed(0) : null;
                    const primaryIsDecimal = usesDecimalOdds(signal.sport);
                    return (
                      <>
                        <p>
                          <strong>Committed</strong> is the worst price the
                          genius guarantees you can get. The floor, not the
                          ceiling: if any sportsbook is offering a better
                          price at settlement, you get credited at that
                          better price instead.
                        </p>
                        <p>
                          <strong>If your pick wins:</strong>{" "}
                          {committedDecimal != null && committedPct != null ? (
                            <>
                              every $100 of notional pays{" "}
                              <strong>${committedPct}</strong> in credit (at
                              the committed price of {formatOdds(committedDecimal, primaryIsDecimal ? "decimal" : "american")}
                              {!primaryIsDecimal && `, which is ${committedDecimal.toFixed(2)} decimal`}).
                              Paid in account credit, not cash.
                            </>
                          ) : (
                            <>
                              you earn account credit at the committed
                              price. Paid in credit, not cash.
                            </>
                          )}
                        </p>
                        <p>
                          <strong>If your pick loses:</strong> the
                          genius&rsquo;s locked collateral pays you{" "}
                          <strong>{slaPct}%</strong> of your notional back as
                          account credit. For every $100 of notional, that&rsquo;s
                          {" "}<strong>${(slaPct).toFixed(0)}</strong>. Paid
                          in credit, not cash.
                        </p>
                        <p>
                          If later results show that multiple sportsbooks
                          beat the committed price, you get credited at the
                          average of those better prices, not just at the
                          promised floor. You never get less than committed.
                        </p>
                        <p>
                          Full spec:{" "}
                          <a
                            href="/docs"
                            className="underline hover:text-green-900"
                          >
                            /docs → Purchase &amp; Settlement
                          </a>
                          .
                        </p>
                      </>
                    );
                  })()}
                </div>
              </details>
              {realLineBooks.length > 0 && (
                <details className="text-xs text-green-700 mt-3">
                  <summary className="cursor-pointer select-none">
                    Per-book prices ({realLineBooks.length})
                  </summary>
                  <ul className="mt-2 space-y-0.5 font-mono">
                    {realLineBooks.map((b) => {
                      const primaryIsDecimal = usesDecimalOdds(signal.sport);
                      const primary = formatOdds(
                        b.odds,
                        primaryIsDecimal ? "decimal" : "american",
                      );
                      return (
                        <li key={b.bookmaker} className="flex justify-between">
                          <span>{b.bookmaker}</span>
                          <span>{primary}</span>
                        </li>
                      );
                    })}
                  </ul>
                </details>
              )}
            </div>
            {!isV2 && (
              <CompletionDecoyLines
                decoyLines={signal.decoyLines}
                realIndex={decryptedPick.realIndex}
              />
            )}
          </div>
        ) : (
          <div className="card text-left mb-8">
            {isV2 ? (
              <p className="text-sm text-slate-500">Decryption key pending. Refresh to check.</p>
            ) : (
              <CompletionDecoyLines
                decoyLines={signal.decoyLines}
                realIndex={null}
                label="Lines (decryption key pending)"
              />
            )}
          </div>
        )}

        <button
          onClick={() => router.push("/idiot")}
          className="btn-primary"
        >
          Back to Dashboard
        </button>
      </div>
    );
  }

  const isProcessing =
    step === "checking_lines" ||
    step === "purchasing_validator" ||
    step === "purchasing_chain" ||
    step === "collecting_shares" ||
    step === "decrypting";

  const stepLabel: Record<string, string> = {
    checking_lines: "Checking line availability at your sportsbooks...",
    purchasing_validator: "Verifying with validators (secure multi-party check)...",
    purchasing_chain: purchaseLoading && !txHash
      ? "Check your wallet — there's a USDC payment to confirm"
      : "Recording purchase on-chain...",
    collecting_shares: "Collecting decryption keys from validators...",
    decrypting: "Decrypting the signal...",
    recovering: "Resuming your purchase (payment already made)...",
  };

  /** Short sub-label shown under the step label during long-running
   * wallet popups. Explains what the user should look for in the popup
   * so they know what's normal. The most common user confusion is raw
   * calldata in the wallet preview — wallets can't decode custom
   * contract functions like Escrow.purchase without Basescan
   * verification, so we tell users up front that the jargon is fine. */
  const stepSubLabel: Record<string, string> = {
    purchasing_chain: purchaseLoading && !txHash
      ? "Your wallet will show a transaction to the Djinn Escrow contract. If it looks like bytecode instead of a readable name, that's because Base Sepolia doesn't decode every custom function — it's still the correct purchase. Review the amount and click Confirm."
      : "",
    purchasing_validator: "This runs while you wait — no wallet popup here.",
    collecting_shares: "No wallet popup needed. Just fetching the decryption keys your purchase earned you.",
  };

  // Progress bar: each step has a weight proportional to its expected duration
  const stepProgress: Record<string, { pct: number; elapsed: string }> = {
    checking_lines: { pct: 5, elapsed: "<1s" },
    purchasing_validator: { pct: 60, elapsed: "~45s" },
    purchasing_chain: { pct: 85, elapsed: "~10s" },
    collecting_shares: { pct: 95, elapsed: "~5s" },
    decrypting: { pct: 98, elapsed: "<1s" },
    recovering: { pct: 50, elapsed: "" },
  };

  return (
    <div className="max-w-3xl mx-auto pb-20 md:pb-0">
      <button
        onClick={() => router.push("/idiot")}
        className="text-sm text-slate-500 hover:text-slate-900 mb-6 transition-colors"
      >
        &larr; Back to Dashboard
      </button>

      <div className="grid md:grid-cols-3 gap-6">
        {/* Signal Info */}
        <div className="md:col-span-2 space-y-6">
          <div className="card">
            <div className="flex items-start justify-between mb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-2xl font-bold text-slate-900">
                    Signal #{truncateAddress(String(idStr ?? ""))}
                  </h1>
                  {signal.minNotional > 0n && signal.minNotional === signal.maxNotional && (
                    <span className="inline-flex items-center rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[10px] font-semibold text-amber-700 uppercase tracking-wide">
                      Exclusive
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-500 mt-1">
                  by {truncateAddress(signal.genius)}
                </p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  isActive
                    ? "bg-green-100 text-green-600 border border-green-200"
                    : "bg-slate-100 text-slate-500 border border-slate-200"
                }`}
              >
                {isActive ? "Active" : signalStatusLabel(signal.status)}
              </span>
            </div>

            {matchedPurchase && (() => {
              const outcomeData = purchaseOutcomeQuery.data;
              // Outcome enum (IDjinn.sol): 0=Pending, 1=Favorable, 2=Unfavorable, 3=Void.
              const outcome = outcomeData?.outcome;
              const audited = outcomeData?.audited ?? false;
              let label = "Pending";
              let detail = "Game has not yet completed; outcome will appear once validators resolve it.";
              let tone = "bg-slate-50 border-slate-200 text-slate-700";
              if (outcome === 1) {
                label = "Favorable (your pick won)";
                detail = audited
                  ? "Settled in an audit batch. Any quality-score credits owed to you have been applied."
                  : "Outcome is locked in; awaiting batch audit settlement before credits / collateral release.";
                tone = "bg-green-50 border-green-200 text-green-800";
              } else if (outcome === 2) {
                label = "Unfavorable (your pick lost)";
                detail = audited
                  ? "Settled. The audit batch quality score reflects this loss."
                  : "Outcome is locked in; the audit batch will settle this and any other resolved purchases together.";
                tone = "bg-red-50 border-red-200 text-red-800";
              } else if (outcome === 3) {
                label = "Void / push";
                detail = "Game pushed or signal voided; no quality impact and notional remains intact.";
                tone = "bg-amber-50 border-amber-200 text-amber-800";
              }
              return (
                <div className={`rounded-lg border p-3 mb-6 ${tone}`}>
                  <p className="text-xs uppercase tracking-wide opacity-70 mb-1">
                    You purchased this signal · Outcome
                  </p>
                  <p className="text-sm font-semibold">{label}</p>
                  <p className="text-xs mt-1 opacity-80">{detail}</p>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-80">
                    <span>Notional ${formatUsdc(matchedPurchase.notional)}</span>
                    <span>Fee paid ${formatUsdc(matchedPurchase.feePaid)}</span>
                    {matchedPurchase.creditUsed > 0n && (
                      <span>Credits used ${formatUsdc(matchedPurchase.creditUsed)}</span>
                    )}
                    <span>{audited ? "Audit settled" : "Audit pending"}</span>
                  </div>
                </div>
              );
            })()}

            <div className="grid grid-cols-2 gap-4 mb-6">
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wide">
                  Sport
                </p>
                <p className="text-sm text-slate-900 font-medium mt-1">
                  {sportLabel(signal.sport)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wide">
                  Signal Fee
                </p>
                <p className="text-sm text-slate-900 font-medium mt-1">
                  {formatBps(signal.maxPriceBps)} of notional
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  ${((100 * Number(signal.maxPriceBps)) / 10_000).toFixed(2)} per $100
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wide">
                  Genius Skin in Game
                </p>
                <p className="text-sm text-slate-900 font-medium mt-1">
                  {formatBps(signal.slaMultiplierBps)}
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Genius has {formatBps(signal.slaMultiplierBps)} of your notional locked as collateral,
                  settled based on audited performance across a batch of signals.
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wide">
                  Pricing
                </p>
                <p className="text-sm text-slate-900 font-medium mt-1">
                  {signal.bpaMode ? "Best Price Available" : "Worst Price Available"}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wide">
                  Expires
                </p>
                <p
                  className={`text-sm font-medium mt-1 ${
                    isExpired ? "text-red-600" : "text-slate-900"
                  }`}
                >
                  {expiresDate.toLocaleString()}
                </p>
              </div>
            </div>

            {/* Lines hidden pre-purchase */}
            <p className="text-xs text-slate-400 italic leading-relaxed">
              {isV2 ? (
                <>
                  This signal hides the genius&apos;s real pick among{" "}
                  <span className="text-slate-600 font-medium">{signal.lineCount} total lines</span>
                  {" "}({signal.lineCount - 1} decoys + 1 real). Decoys are real bookmaker lines from
                  multiple games and sports, with odds slightly perturbed (&ldquo;jiggered&rdquo;) so no line
                  stands out statistically — even validators can&apos;t tell which is real. Decoy
                  content is off-chain; only the line count and a content hash are committed
                  on-chain. The real pick is revealed only to you, only after your purchase
                  completes.
                </>
              ) : (
                <>
                  This signal hides the genius&apos;s real pick among{" "}
                  <span className="text-slate-600 font-medium">{signal.decoyLines.length} total encrypted lines</span>
                  {" "}({signal.decoyLines.length - 1} decoys + 1 real). Decoy lines are stored
                  on-chain alongside the encrypted pick. The real signal is revealed only to you,
                  only after your purchase completes.
                </>
              )}
            </p>
          </div>

        </div>

        {/* Purchase Panel */}
        <div className="space-y-6">
          <div className="card">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">
              Purchase Signal
            </h2>

            {isActive && escrowBalance !== undefined && (
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 mb-4">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-slate-500">Your Escrow Balance</p>
                  <p className="text-sm font-medium text-slate-900">
                    ${formatUsdc(escrowBalance)}
                  </p>
                </div>
                {depositMsg && (
                  <p className="text-xs text-green-600 mt-1">{depositMsg}</p>
                )}
                <div className="flex gap-2 mt-2">
                  <input
                    id="depositEscrow"
                    type="number"
                    inputMode="decimal"
                    placeholder="Amount"
                    className="input flex-1 text-xs py-1.5"
                    value={depositAmt}
                    onChange={(e) => setDepositAmt(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn-primary text-xs py-1.5 px-3 whitespace-nowrap"
                    disabled={depositLoading || !depositAmt}
                    onClick={async () => {
                      setDepositMsg(null);
                      const pauseErr = checkPause("escrow", "Deposit");
                      if (pauseErr) { setDepositMsg(pauseErr); return; }
                      try {
                        const result = await depositEscrow(parseUsdc(depositAmt));
                        if (result === "approved") {
                          setDepositMsg("USDC approved! Click Deposit again.");
                          return;
                        }
                        setDepositAmt("");
                        setDepositMsg(`Deposited $${depositAmt}`);
                        refreshEscrow();
                      } catch (err) {
                        setDepositMsg(humanizeError(err, "Deposit failed"));
                      }
                    }}
                  >
                    {depositLoading ? "..." : "Deposit"}
                  </button>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Wallet: ${formatUsdc(walletUsdc)} USDC
                </p>
              </div>
            )}

            {signalAvailable === null && isActive && (
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 mb-4">
                <p className="text-xs text-slate-500 animate-pulse">Checking signal availability...</p>
              </div>
            )}

            {signalAvailable === false && isActive && !isProcessing && (
              <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 mb-4" role="alert">
                <p className="text-sm font-medium text-amber-800 mb-1">Signal Temporarily Unavailable</p>
                <p className="text-xs text-amber-700">
                  Validators are still distributing encryption key shares for this signal.
                  This page re-checks automatically every 15 seconds. If you just created
                  this signal, wait a moment for the network to sync.
                </p>
              </div>
            )}

            {linesAvailable === null && isActive && signalAvailable !== false && (
              <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 mb-4">
                <p className="text-xs text-blue-600 animate-pulse">Checking if lines are available at sportsbooks...</p>
              </div>
            )}

            {linesAvailable === true && isActive && (
              <div className="rounded-lg bg-green-50 border border-green-200 p-3 mb-4">
                <p className="text-xs text-green-700">Sportsbook lines active. You can attempt a purchase.</p>
              </div>
            )}

            {linesAvailable === false && isActive && (
              <div className="rounded-lg bg-red-50 border border-red-200 p-4 mb-4" role="alert">
                <p className="text-sm font-medium text-red-800 mb-1">Game Started or Lines Unavailable</p>
                <p className="text-xs text-red-700">
                  {linesReason || "The lines for this signal are no longer available at sportsbooks. The game may have started or lines may have moved."}
                </p>
                <button
                  onClick={() => router.push("/idiot/browse")}
                  className="mt-2 text-xs text-red-600 hover:text-red-800 underline font-medium"
                >
                  Browse other signals
                </button>
              </div>
            )}

            {isV2 && isActive && (
              <div className="mb-4">
                <BookPreferences />
              </div>
            )}

            {address && signal.genius && address.toLowerCase() === signal.genius.toLowerCase() && (
              <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 mb-4" role="status">
                <p className="text-xs text-amber-700 font-medium">
                  Heads up: this is your own signal.
                </p>
              </div>
            )}

            {!isActive ? (
              <p className="text-sm text-slate-500">
                This signal is no longer available for purchase.
              </p>
            ) : (
              <form onSubmit={handlePurchase} className="space-y-4">
                <div>
                  <label htmlFor="notional" className="label">Notional (USDC)</label>
                  {signal.maxNotional > 0n && (
                    <div className="mb-2">
                      <div className="flex justify-between text-xs text-slate-500 mb-1">
                        <span>${formatUsdc(notionalFilled)} filled</span>
                        <span>${formatUsdc(signal.maxNotional)} capacity</span>
                      </div>
                      <div className="w-full bg-slate-100 rounded-full h-2">
                        <div
                          className="bg-idiot-500 h-2 rounded-full transition-all"
                          style={{ width: `${Math.min(100, Number(notionalFilled * 100n / signal.maxNotional))}%` }}
                        />
                      </div>
                      {notionalFilled >= signal.maxNotional && (
                        <p className="text-xs text-red-500 mt-1 font-medium">This signal is fully filled</p>
                      )}
                    </div>
                  )}
                  {(() => {
                    const minVal = signal.minNotional > 0n ? Number(signal.minNotional) / 1e6 : 1;
                    const remaining = signal.maxNotional > 0n ? Number(signal.maxNotional - notionalFilled) / 1e6 : 0;
                    const maxVal = signal.maxNotional > 0n ? remaining : undefined;
                    const hasRange = maxVal !== undefined && maxVal > minVal;
                    const isFull = signal.maxNotional > 0n && notionalFilled >= signal.maxNotional;
                    return (
                      <>
                        {hasRange && (
                          <div className="mb-2">
                            <input
                              type="range"
                              min={minVal}
                              max={maxVal}
                              step={0.01}
                              value={notional || minVal}
                              onChange={(e) => setNotional(e.target.value)}
                              className="w-full h-2 bg-slate-200 rounded-full appearance-none cursor-pointer accent-idiot-500"
                              disabled={isFull}
                            />
                          </div>
                        )}
                        <div className="flex gap-2 mb-2">
                          {maxVal !== undefined && maxVal === minVal ? (
                            <button
                              type="button"
                              onClick={() => setNotional(String(maxVal))}
                              disabled={isFull}
                              className={`flex-1 rounded-lg border py-1.5 text-xs font-medium transition-colors ${
                                notional === String(maxVal)
                                  ? "border-idiot-300 bg-idiot-50 text-idiot-700"
                                  : "border-slate-200 text-slate-500 hover:border-idiot-300 hover:text-idiot-600"
                              }`}
                            >
                              ${maxVal.toFixed(2)}
                            </button>
                          ) : (
                            <>
                              {minVal > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setNotional(String(minVal))}
                                  disabled={isFull}
                                  className={`flex-1 rounded-lg border py-1.5 text-xs font-medium transition-colors ${
                                    notional === String(minVal)
                                      ? "border-idiot-300 bg-idiot-50 text-idiot-700"
                                      : "border-slate-200 text-slate-500 hover:border-idiot-300 hover:text-idiot-600"
                                  }`}
                                >
                                  Min ${minVal.toFixed(2)}
                                </button>
                              )}
                              {maxVal !== undefined && (
                                <button
                                  type="button"
                                  onClick={() => setNotional(String(maxVal))}
                                  disabled={isFull}
                                  className={`flex-1 rounded-lg border py-1.5 text-xs font-medium transition-colors ${
                                    notional === String(maxVal)
                                      ? "border-idiot-300 bg-idiot-50 text-idiot-700"
                                      : "border-slate-200 text-slate-500 hover:border-idiot-300 hover:text-idiot-600"
                                  }`}
                                >
                                  Max ${maxVal.toFixed(2)}
                                </button>
                              )}
                            </>
                          )}
                        </div>
                        <input
                          id="notional"
                          type="number"
                          value={notional}
                          onChange={(e) => setNotional(e.target.value)}
                          placeholder={maxVal ? maxVal.toFixed(2) : "100.00"}
                          min={minVal}
                          step="0.01"
                          max={maxVal}
                          className="input"
                          required
                          disabled={isFull}
                        />
                        <p className="text-xs text-slate-500 mt-1">
                          Your notional. Determines both the signal fee you pay and how much collateral the Genius has riding on this pick.
                        </p>
                      </>
                    );
                  })()}
                </div>


                {notional && (
                  <div className="rounded-lg bg-slate-50 p-3 space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">You pay (fee)</span>
                      <span className="text-slate-900 font-medium">
                        $
                        {(
                          (Number(notional) * Number(signal.maxPriceBps)) /
                          10_000
                        ).toFixed(2)}
                      </span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">
                        Genius collateral locked
                      </span>
                      <span className="text-slate-900 font-medium">
                        $
                        {(
                          (Number(notional) *
                            Number(signal.slaMultiplierBps)) /
                          10_000
                        ).toFixed(2)}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 pt-1 border-t border-slate-200">
                      Collateral is settled based on the Genius&apos;s audited quality score across a batch of signals, not on any single pick.
                      {" "}Any Djinn Credits in your account are applied automatically to reduce the USDC portion of the fee.
                    </p>
                  </div>
                )}

                {(purchaseError || stepError) && (
                  <div className="rounded-lg bg-red-50 border border-red-200 p-4" role="alert">
                    <p className="text-sm text-red-700 font-medium">
                      {purchaseError || stepError}
                    </p>
                    {step === "idle" && !isProcessing && hasPendingDecryption && (
                      <button
                        type="button"
                        onClick={() => runDecryptionRecovery()}
                        className="mt-3 inline-flex items-center gap-1 rounded-md bg-red-600 hover:bg-red-700 px-3 py-1.5 text-sm font-medium text-white transition-colors"
                      >
                        Retry decryption
                      </button>
                    )}
                    {step === "idle" && !isProcessing && !hasPendingDecryption && (
                      <p className="text-xs text-red-500 mt-2">
                        You can try again by clicking the button below.
                      </p>
                    )}
                  </div>
                )}

                {isProcessing && (
                  <div className="rounded-lg bg-blue-50 border border-blue-200 p-4" aria-live="polite">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-sm font-medium text-blue-700">
                        {stepLabel[step] ?? "Processing..."}
                      </p>
                      {stepProgress[step]?.elapsed && (
                        <span className="text-xs text-blue-500">{stepProgress[step].elapsed}</span>
                      )}
                    </div>
                    {stepSubLabel[step] && (
                      <p className="text-xs text-blue-600 mb-3 leading-relaxed">
                        {stepSubLabel[step]}
                      </p>
                    )}
                    <div className="w-full bg-blue-200 rounded-full h-1.5">
                      <div
                        className="bg-blue-600 h-1.5 rounded-full transition-all duration-1000 ease-out"
                        style={{ width: `${stepProgress[step]?.pct ?? 50}%` }}
                      />
                    </div>
                    <div className="flex justify-between mt-2 text-xs text-blue-500">
                      <span>Lines</span>
                      <span>Verify</span>
                      <span>Pay</span>
                      <span>Decrypt</span>
                    </div>
                    {txHash && (
                      <div className="mt-3 pt-3 border-t border-blue-200">
                        <a
                          href={txUrl(txHash)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-blue-700 hover:text-blue-900 inline-flex items-center gap-1.5"
                        >
                          <span className="font-mono">{txHash.slice(0, 10)}…{txHash.slice(-8)}</span>
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                          </svg>
                          <span>View on Basescan</span>
                        </a>
                      </div>
                    )}
                  </div>
                )}

                <button
                  ref={purchaseBtnRef}
                  type="submit"
                  disabled={
                    isProcessing ||
                    purchaseLoading ||
                    signalAvailable === false ||
                    linesAvailable === false ||
                    (signal.maxNotional > 0n && notionalFilled >= signal.maxNotional)
                  }
                  className="btn-primary w-full py-3"
                >
                  {isProcessing
                    ? "Processing..."
                    : linesAvailable === false
                      ? "Game Started"
                      : signalAvailable === false
                        ? "Unavailable"
                        : signal.maxNotional > 0n && notionalFilled >= signal.maxNotional
                          ? "Fully Filled"
                          : "Purchase Signal"}
                </button>
              </form>
            )}
          </div>

          {/* Genius info sidebar */}
          <div className="card">
            <h3 className="text-sm font-medium text-slate-500 mb-3">
              Genius Stats
            </h3>
            <div className="space-y-3">
              <div>
                <p className="text-xs text-slate-500">Quality Score</p>
                <div className="mt-1">
                  <QualityScore score={aggregateQualityScore} size="sm" />
                </div>
              </div>
              <div>
                <p className="text-xs text-slate-500">Total Signals</p>
                <p className="text-sm text-slate-900 font-medium">
                  {geniusSignals.length}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Audit Count</p>
                <p className="text-sm text-slate-900 font-medium">
                  {geniusAudits.length}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Sticky mobile purchase bar — hidden when form submit button is in view */}
      {isActive && !isProcessing && !purchaseBtnVisible && (
        <div className="fixed bottom-0 left-0 right-0 md:hidden bg-white/95 backdrop-blur-sm border-t border-slate-200 px-4 py-3 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)] z-10">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm">
              {notional ? (
                <span className="text-slate-900 font-medium">
                  Fee: ${((Number(notional) * Number(signal.maxPriceBps)) / 10_000).toFixed(2)}
                </span>
              ) : (
                <span className="text-slate-500">Enter notional above</span>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                // Scroll to purchase form
                document.getElementById("notional")?.scrollIntoView({ behavior: "smooth", block: "center" });
              }}
              className="btn-idiot whitespace-nowrap"
            >
              Purchase Signal
            </button>
          </div>
        </div>
      )}

      {isProcessing && (
        <div className="fixed bottom-0 left-0 right-0 md:hidden bg-blue-50 border-t border-blue-200 px-4 py-3 z-10">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-blue-700 font-medium">
              {stepLabel[step] ?? "Processing..."}
            </p>
            {stepProgress[step]?.elapsed && (
              <span className="text-xs text-blue-500">{stepProgress[step].elapsed}</span>
            )}
          </div>
          <div className="w-full bg-blue-200 rounded-full h-1">
            <div
              className="bg-blue-600 h-1 rounded-full transition-all duration-1000 ease-out"
              style={{ width: `${stepProgress[step]?.pct ?? 50}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible decoy lines for the completion screen
// ---------------------------------------------------------------------------
function CompletionDecoyLines({
  decoyLines,
  realIndex,
  label,
}: {
  decoyLines: string[];
  realIndex: number | null;
  label?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 text-sm font-medium text-slate-500 mb-2 hover:text-slate-700 transition-colors"
      >
        <span>{label || `All ${decoyLines.length} Lines`}</span>
        <svg
          className={`w-3.5 h-3.5 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="space-y-1">
          {decoyLines.map((raw, i) => {
            const structured = parseLine(raw);
            const display = structured ? formatLine(structured) : raw;
            const isReal = realIndex !== null && i + 1 === realIndex;
            return (
              <p
                key={i}
                className={`text-sm font-mono rounded px-3 py-2 ${
                  isReal
                    ? "bg-green-100 text-green-800 font-bold"
                    : "bg-slate-50 text-slate-500"
                }`}
              >
                {i + 1}. {display}
                {isReal && " \u2190 REAL"}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}
