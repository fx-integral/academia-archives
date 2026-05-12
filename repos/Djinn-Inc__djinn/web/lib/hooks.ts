"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ethers } from "ethers";
import { useAccount, useWalletClient } from "wagmi";
import { parseAbi, keccak256, encodePacked, type Hex } from "viem";
import { base, baseSepolia } from "viem/chains";
import { waitForTransactionReceipt, getBlockNumber } from "@wagmi/core";
import { wagmiConfig } from "../app/providers";
import {
  getSignalCommitmentContract,
  getEscrowContract,
  getCollateralContract,
  getCreditLedgerContract,
  getAccountContract,
  getAuditContract,
  getUsdcContract,
  ADDRESSES,
  ACCOUNT_ABI,
} from "./contracts";
import type { Signal, CommitParams } from "./types";

// ---------------------------------------------------------------------------
// Debug logging — only emits in development
// ---------------------------------------------------------------------------

const isDev = process.env.NODE_ENV === "development";
const debug: (...args: unknown[]) => void = isDev
  ? (...args: unknown[]) => console.log(...args)
  : () => {};

// ---------------------------------------------------------------------------
// Error humanization — turn raw contract errors into readable messages
// ---------------------------------------------------------------------------

const REVERT_PATTERNS: [RegExp, string][] = [
  [/missing revert data/i, "Contract not deployed. The protocol contracts need to be deployed before you can transact."],
  [/could not detect network/i, "Cannot connect to the blockchain. Check your network connection."],
  [/CALL_EXCEPTION.*data=null/i, "Contract not deployed. The protocol contracts need to be deployed before you can transact."],
  [/InsufficientFreeCollateral/i, "Genius doesn't have enough collateral deposited for this signal's SLA"],
  [/InsufficientBalance/i, "Insufficient escrow balance: deposit more USDC before purchasing"],
  [/Insufficient collateral/i, "You don't have enough collateral deposited"],
  [/Insufficient balance/i, "Insufficient USDC balance"],
  [/Insufficient escrow/i, "Not enough funds in your escrow account"],
  [/SignalNotActive/i, "This signal is no longer active"],
  [/SignalExpired/i, "This signal has expired"],
  [/Signal expired/i, "This signal has expired"],
  [/Signal does not exist/i, "Signal not found on-chain"],
  [/AlreadyPurchased/i, "You've already purchased this signal"],
  [/Already purchased/i, "You've already purchased this signal"],
  [/Already committed/i, "This signal was already committed"],
  [/NotionalTooSmall/i, "Notional amount is below the minimum"],
  [/NotionalTooLarge/i, "Notional amount exceeds the maximum"],
  [/NotionalExceedsSignalMax/i, "Notional exceeds this signal's remaining capacity"],
  [/OddsOutOfRange/i, "Odds are out of the valid range"],
  [/ZeroAmount/i, "Amount cannot be zero"],
  [/ContractNotSet/i, "Protocol contract not configured (contact admin)"],
  [/CycleSignalLimitReached/i, "You've reached the signal purchase limit for this genius (10 max per audit batch)"],
  [/InsufficientFreeCollateral/i, "Genius does not have enough free collateral for this signal"],
  [/Not genius/i, "Only the signal creator can perform this action"],
  [/Transfer amount exceeds allowance/i, "USDC approval needed, please approve the transfer first"],
  [/Transfer amount exceeds balance/i, "Insufficient USDC balance in your wallet"],
  [/user rejected/i, "Transaction cancelled by user"],
  [/user denied/i, "Transaction cancelled by user"],
  [/ACTION_REJECTED/i, "Transaction cancelled by user"],
  [/nonce.*already.*used/i, "Transaction nonce conflict, please wait and try again"],
  [/replacement.*underpriced/i, "Gas price too low, try increasing gas"],
  [/insufficient funds for gas/i, "Not enough ETH to cover gas fees. Get testnet ETH from a faucet."],
  [/No request found/i, "Wallet lost track of the request, please try again"],
  [/chain.*mismatch|wrong.*network|Wrong network/i, "Wrong network: switch to Base Sepolia in your wallet settings."],
  [/Request is being rate limited|429 too many requests|rate.?limit(ed)?/i, "RPC provider rate-limited this transaction. Wait 10-30 seconds and try again."],
  [/execution reverted/i, "Transaction reverted on-chain, check your balances and try again"],
];

/** Convert a raw transaction error to a user-friendly message. */
export function humanizeError(err: unknown, fallback = "Transaction failed"): string {
  if (!(err instanceof Error)) return fallback;
  const msg = err.message;

  for (const [pattern, readable] of REVERT_PATTERNS) {
    if (pattern.test(msg)) return readable;
  }

  // Extract revert reason if present
  const revertMatch = msg.match(/reason="([^"]+)"/);
  if (revertMatch) return revertMatch[1];

  // Extract error string from reverted call
  const execMatch = msg.match(/execution reverted:\s*"?([^"]+)"?/);
  if (execMatch) return execMatch[1];

  // For generic contract errors, clean up the message
  // But preserve validator/miner distribution errors (they have useful detail)
  if (msg.length > 200 && !msg.includes("distribution failed")) return fallback;

  return msg;
}

// ---------------------------------------------------------------------------
// Chain ID — expected chain for all transactions (Base Sepolia: 84532, Base: 8453)
// ---------------------------------------------------------------------------

const EXPECTED_CHAIN_ID = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? "84532");
const expectedChain = EXPECTED_CHAIN_ID === 8453 ? base : baseSepolia;

/** Throw a descriptive error if the wallet is on the wrong chain. */
function assertCorrectChain(walletClient: { chain?: { id: number } }) {
  const chainId = walletClient.chain?.id;
  // Only block if we positively know the chain is wrong. Skip if chain info
  // is unavailable (e.g. in tests or wallets that don't expose it).
  if (chainId !== undefined && chainId !== EXPECTED_CHAIN_ID) {
    throw new Error(
      `Wrong network: please switch to ${expectedChain.name} (chain ID ${EXPECTED_CHAIN_ID}) in your wallet.`
    );
  }
}

// ---------------------------------------------------------------------------
// Read-only provider — uses public RPC for reliable reads
// ---------------------------------------------------------------------------

const READ_RPC_URL = process.env.NEXT_PUBLIC_BASE_RPC_URL ?? "https://sepolia.base.org";
let _readProvider: ethers.JsonRpcProvider | null = null;

export function getReadProvider(): ethers.JsonRpcProvider {
  if (!_readProvider) {
    _readProvider = new ethers.JsonRpcProvider(READ_RPC_URL, EXPECTED_CHAIN_ID, { staticNetwork: true });
  }
  return _readProvider;
}

// ---------------------------------------------------------------------------
// Provider & signer hooks — uses wagmi wallet client for signing
// ---------------------------------------------------------------------------

export function useEthersProvider(): ethers.BrowserProvider | null {
  const { data: walletClient } = useWalletClient();
  // walletClient IS the EIP-1193 provider — its request() method routes
  // signing through the wallet popup. walletClient.transport would only give
  // read-only RPC access and cannot sign.
  return useMemo(() => {
    if (!walletClient) return null;
    return new ethers.BrowserProvider(
      walletClient as unknown as ethers.Eip1193Provider,
      EXPECTED_CHAIN_ID,
    );
  }, [walletClient]);
}

export function useEthersSigner(): ethers.Signer | null {
  const provider = useEthersProvider();
  const [signer, setSigner] = useState<ethers.Signer | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (provider) {
      provider.getSigner().then((s) => {
        if (!cancelled) setSigner(s);
      }).catch((err) => {
        console.error("[useEthersSigner] getSigner failed:", err);
        if (!cancelled) setSigner(null);
      });
    } else {
      setSigner(null);
    }
    return () => { cancelled = true; };
  }, [provider]);

  return signer;
}

/** Check if the wallet is on the expected chain. */
export function useChainId(): { chainId: number | null; isCorrectChain: boolean } {
  const { chainId: wagmiChainId } = useAccount();
  const chainId = wagmiChainId ? Number(wagmiChainId) : null;
  return { chainId, isCorrectChain: chainId === EXPECTED_CHAIN_ID };
}

// ---------------------------------------------------------------------------
// Protocol-pause state — reads paused() on every contract whose user-facing
// mutations are gated by whenNotPaused. Surfaced in the Layout maintenance
// banner so a live pause (incident response) yields a clear "we're down for
// maintenance" signal instead of silent wallet-popup-then-revert. Keep the
// query key stable across addresses — pause state is protocol-wide.
// ---------------------------------------------------------------------------

export interface ProtocolPausedState {
  anyPaused: boolean;
  byContract: {
    escrow: boolean;
    collateral: boolean;
    creditLedger: boolean;
    account: boolean;
    signalCommitment: boolean;
    audit: boolean;
  };
  loading: boolean;
}

export function useProtocolPaused(): ProtocolPausedState {
  const query = useQuery({
    queryKey: ["protocol-paused"] as const,
    queryFn: async () => {
      const provider = getReadProvider();
      // Each read is wrapped in try/catch so one misconfigured address
      // (e.g. CreditLedger not yet upgraded to expose paused()) can't mask
      // a real pause on another contract. A throw here would render the
      // banner "unknown" during an actual incident — the worst possible
      // UX. Treat read failure as "not paused" and let the pre-flight
      // tx simulation surface the revert if it actually is paused.
      const readPaused = async (
        getter: (p: ethers.Provider) => ethers.Contract,
      ): Promise<boolean> => {
        try {
          const c = getter(provider);
          const p = await c.paused();
          return Boolean(p);
        } catch {
          return false;
        }
      };
      const [escrow, collateral, creditLedger, account, signalCommitment, audit] =
        await Promise.all([
          readPaused(getEscrowContract),
          readPaused(getCollateralContract),
          readPaused(getCreditLedgerContract),
          readPaused(getAccountContract),
          readPaused(getSignalCommitmentContract),
          readPaused(getAuditContract),
        ]);
      return { escrow, collateral, creditLedger, account, signalCommitment, audit };
    },
    // 30s staleTime — pause events are rare but when they fire we want the
    // banner visible within one query-refresh window. refetchInterval keeps
    // the cache fresh even on an idle tab; without it, a user who held the
    // tab open for minutes could click a mutation button on a cached
    // "not paused" state right after an admin pause, firing the wallet
    // popup before the banner caught up. Tab-hidden polling is disabled
    // (default) so background tabs don't burn RPC.
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });

  const byContract = query.data ?? {
    escrow: false,
    collateral: false,
    creditLedger: false,
    account: false,
    signalCommitment: false,
    audit: false,
  };
  const anyPaused =
    byContract.escrow ||
    byContract.collateral ||
    byContract.creditLedger ||
    byContract.account ||
    byContract.signalCommitment ||
    byContract.audit;

  return {
    anyPaused,
    byContract,
    loading: query.isPending,
  };
}

export type PauseSubsystem = keyof ProtocolPausedState["byContract"];

// Returns a function that, given a subsystem name and a user-facing action
// label ("Deposit", "Purchase", ...), returns an error message when that
// contract is currently paused or null when it is safe to proceed. Mutation
// handlers call this at the top and short-circuit with setTxError + early
// return — avoids firing the wallet popup for a tx that would revert with
// `EnforcedPause` anyway. The underlying query is shared with the Layout
// banner, so no extra RPC traffic.
export function useMutationGate(): (
  subsystem: PauseSubsystem,
  action: string,
) => string | null {
  const { byContract } = useProtocolPaused();
  return (subsystem, action) => {
    if (byContract[subsystem]) {
      return `${action} temporarily unavailable: the protocol is paused for maintenance. Please try again shortly.`;
    }
    return null;
  };
}

// ---------------------------------------------------------------------------
// Wallet USDC balance hook — raw USDC in the user's wallet (not deposited)
// ---------------------------------------------------------------------------

export function useWalletUsdcBalance(address: string | undefined) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["wallet-usdc-balance", address ?? "none"] as const,
    [address],
  );

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      try {
        const usdc = getUsdcContract(getReadProvider());
        const bal = await usdc.balanceOf(address!);
        return BigInt(bal);
      } catch {
        // Silently fail — wallet balance is informational
        return 0n;
      }
    },
    enabled: Boolean(address),
    staleTime: 15_000,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey }),
    [queryClient, queryKey],
  );

  return {
    balance: (query.data ?? 0n) as bigint,
    loading: query.isFetching,
    refresh,
  };
}

// ---------------------------------------------------------------------------
// Escrow balance hook
// ---------------------------------------------------------------------------

export function useEscrowBalance(address: string | undefined) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["escrow-balance", address ?? "none"] as const,
    [address],
  );

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const contract = getEscrowContract(getReadProvider());
      const bal = await contract.getBalance(address!);
      return BigInt(bal);
    },
    enabled: Boolean(address),
    staleTime: 15_000,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey }),
    [queryClient, queryKey],
  );

  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch escrow balance"
        : null;

  return {
    balance: (query.data ?? 0n) as bigint,
    loading: query.isFetching,
    refresh,
    error,
  };
}

// ---------------------------------------------------------------------------
// Credit balance hook
// ---------------------------------------------------------------------------

export function useCreditBalance(address: string | undefined) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["credit-balance", address ?? "none"] as const,
    [address],
  );

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const contract = getCreditLedgerContract(getReadProvider());
      const bal = await contract.balanceOf(address!);
      return BigInt(bal);
    },
    enabled: Boolean(address),
    staleTime: 15_000,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey }),
    [queryClient, queryKey],
  );

  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch credit balance"
        : null;

  return {
    balance: (query.data ?? 0n) as bigint,
    loading: query.isFetching,
    refresh,
    error,
  };
}

// ---------------------------------------------------------------------------
// Collateral hooks
// ---------------------------------------------------------------------------

export function useCollateral(address: string | undefined) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["collateral", address ?? "none"] as const,
    [address],
  );

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const contract = getCollateralContract(getReadProvider());
      const [d, l, a] = await Promise.all([
        contract.getDeposit(address!),
        contract.getLocked(address!),
        contract.getAvailable(address!),
      ]);
      return {
        deposit: BigInt(d),
        locked: BigInt(l),
        available: BigInt(a),
      };
    },
    enabled: Boolean(address),
    staleTime: 15_000,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey }),
    [queryClient, queryKey],
  );

  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to fetch collateral"
        : null;

  const data = query.data;
  return {
    deposit: (data?.deposit ?? 0n) as bigint,
    locked: (data?.locked ?? 0n) as bigint,
    available: (data?.available ?? 0n) as bigint,
    loading: query.isFetching,
    refresh,
    error,
  };
}

// ---------------------------------------------------------------------------
// Signal query hook
// ---------------------------------------------------------------------------

export function useSignal(signalId: bigint | undefined) {
  const queryKey = useMemo(
    () => ["signal", signalId !== undefined ? signalId.toString() : "none"] as const,
    [signalId],
  );

  const query = useQuery({
    queryKey,
    queryFn: async (): Promise<Signal> => {
      const contract = getSignalCommitmentContract(getReadProvider());
      const toBigInt = (v: unknown): bigint => {
        if (typeof v === "bigint") return v;
        if (typeof v === "number" || typeof v === "string") return BigInt(v);
        return 0n;
      };
      const raw = (await contract.getSignal(signalId!)) as Record<string, unknown>;
      const parsed: Signal = {
        genius: String(raw.genius ?? ""),
        encryptedBlob: String(raw.encryptedBlob ?? ""),
        commitHash: String(raw.commitHash ?? ""),
        sport: String(raw.sport ?? ""),
        maxPriceBps: toBigInt(raw.maxPriceBps),
        slaMultiplierBps: toBigInt(raw.slaMultiplierBps),
        maxNotional: toBigInt(raw.maxNotional),
        minNotional: toBigInt(raw.minNotional),
        expiresAt: toBigInt(raw.expiresAt),
        decoyLines: Array.isArray(raw.decoyLines) ? raw.decoyLines.map(String) : [],
        availableSportsbooks: Array.isArray(raw.availableSportsbooks) ? raw.availableSportsbooks.map(String) : [],
        status: Number(raw.status ?? 0),
        createdAt: toBigInt(raw.createdAt),
        linesHash: String(raw.linesHash || "0x" + "0".repeat(64)),
        lineCount: Number(raw.lineCount || 0),
        bpaMode: Boolean(raw.bpaMode),
      };
      // genius=0x0 or empty sport means the signal doesn't exist on-chain.
      // Throw so TanStack retries (transient RPC) before giving up.
      if (parsed.genius === "0x0000000000000000000000000000000000000000" || !parsed.sport) {
        throw new Error("Signal not found on-chain");
      }
      return parsed;
    },
    enabled: signalId !== undefined,
    retry: 2,
    retryDelay: 3000,
    staleTime: 30_000,
  });

  const error =
    query.error instanceof Error
      ? query.error.message
      : query.error
        ? "Failed to load signal"
        : null;

  return {
    signal: query.data ?? null,
    loading: signalId !== undefined && query.isPending,
    error,
  };
}

// ---------------------------------------------------------------------------
// Gas estimation utility
// ---------------------------------------------------------------------------

export interface GasEstimate {
  gasLimit: bigint;
  gasPrice: bigint;
  totalCostWei: bigint;
  totalCostEth: string; // Human-readable ETH cost
}

/** Estimate gas for a contract method call. Returns null if estimation fails. */
export async function estimateGas(
  contract: ethers.Contract,
  method: string,
  args: unknown[],
): Promise<GasEstimate | null> {
  try {
    const provider = contract.runner as ethers.Signer;
    const gasLimit = await contract[method].estimateGas(...args);
    const feeData = await (provider as unknown as { provider: ethers.Provider }).provider.getFeeData();
    const gasPrice = feeData.gasPrice ?? feeData.maxFeePerGas ?? 0n;
    const totalCostWei = gasLimit * gasPrice;
    const totalCostEth = ethers.formatEther(totalCostWei);

    return {
      gasLimit,
      gasPrice,
      totalCostWei,
      totalCostEth,
    };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Viem ABI fragments for write operations
// ---------------------------------------------------------------------------

const ERC20_ABI = parseAbi([
  "function approve(address spender, uint256 amount) returns (bool)",
  "function balanceOf(address owner) view returns (uint256)",
  "function nonces(address owner) view returns (uint256)",
  "function name() view returns (string)",
  "function version() view returns (string)",
  "function DOMAIN_SEPARATOR() view returns (bytes32)",
]);

const ESCROW_ABI = parseAbi([
  "function deposit(uint256 amount)",
  "function withdraw(uint256 amount)",
  "function purchase(uint256 signalId, uint256 notional, uint256 odds) returns (uint256 purchaseId)",
  "function depositWithPermit(uint256 amount, uint256 deadline, uint8 v, bytes32 r, bytes32 s)",
  "function supportsFeature(bytes32 featureId) view returns (bool)",
]);

// Feature ID for Escrow.supportsFeature(). Mirrors the Solidity constant
// in contracts/src/Escrow.sol:603 (`keccak256("DEPOSIT_WITH_PERMIT")`).
// Lazily computed on first use so test suites that mock the viem module
// at import time don't crash before setting up their own mocks.
let _featureDepositWithPermit: Hex | null = null;
function getFeatureDepositWithPermitId(): Hex {
  if (!_featureDepositWithPermit) {
    _featureDepositWithPermit = keccak256(
      encodePacked(["string"], ["DEPOSIT_WITH_PERMIT"]),
    );
  }
  return _featureDepositWithPermit;
}

const COLLATERAL_ABI = parseAbi([
  "function deposit(uint256 amount)",
  "function withdraw(uint256 amount)",
]);

const SIGNAL_COMMITMENT_VIEM_ABI = parseAbi([
  "function commit((uint256 signalId, bytes encryptedBlob, bytes32 commitHash, string sport, uint256 maxPriceBps, uint256 slaMultiplierBps, uint256 maxNotional, uint256 minNotional, uint256 expiresAt, string[] decoyLines, string[] availableSportsbooks, bytes32 linesHash, uint16 lineCount, bool bpaMode) p)",
  "function cancelSignal(uint256 signalId)",
]);

// V2 contract signature: earlyExit(address, address, uint256[] purchaseIds).
// The 2-arg form was a stale ABI from before queue-based audits shipped;
// every UI early-exit click was silently encoding-mismatched and the tx
// never landed. Fixed 2026-05-01.
const AUDIT_VIEM_ABI = parseAbi([
  "function earlyExit(address genius, address idiot, uint256[] purchaseIds)",
]);

/** Wait for a tx hash to be confirmed, throw if reverted. */
async function waitForTx(hash: Hex): Promise<void> {
  const receipt = await waitForTransactionReceipt(wagmiConfig, {
    hash,
    timeout: 120_000, // 2 minutes — prevents indefinite hang with Coinbase Smart Wallet
  });
  if (receipt.status === "reverted") throw new Error("Transaction reverted on-chain");
}

// ---------------------------------------------------------------------------
// Transaction hooks
// ---------------------------------------------------------------------------

export function useCommitSignal() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);

  const commit = useCallback(
    async (params: CommitParams) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      setTxHash(null);
      try {
        const signalCommitmentAddr = ADDRESSES.signalCommitment as Hex;

        debug("[commit-signal] committing signal", params.signalId.toString());
        const hash = await walletClient.writeContract({
          address: signalCommitmentAddr,
          abi: SIGNAL_COMMITMENT_VIEM_ABI,
          functionName: "commit",
          account: address,
          chain: expectedChain,
          args: [{
            signalId: params.signalId,
            encryptedBlob: params.encryptedBlob as Hex,
            commitHash: params.commitHash as Hex,
            sport: params.sport,
            maxPriceBps: params.maxPriceBps,
            slaMultiplierBps: params.slaMultiplierBps,
            maxNotional: params.maxNotional,
            minNotional: params.minNotional,
            expiresAt: params.expiresAt,
            decoyLines: params.decoyLines,
            availableSportsbooks: params.availableSportsbooks,
            linesHash: (params.linesHash || "0x" + "0".repeat(64)) as Hex,
            lineCount: params.lineCount || 0,
            bpaMode: params.bpaMode || false,
          }],
        });
        debug("[commit-signal] tx:", hash);
        setTxHash(hash);
        await waitForTx(hash);
        return hash;
      } catch (err) {
        console.error("[commit-signal] FAILED:", err);
        setError(humanizeError(err));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address]
  );

  return { commit, loading, error, txHash };
}

export function usePurchaseSignal() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);

  const purchase = useCallback(
    async (signalId: bigint, notional: bigint, odds: bigint) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      setTxHash(null);
      try {
        const escrowAddr = ADDRESSES.escrow as Hex;

        debug("[purchase-signal] purchasing signal", signalId.toString());
        const hash = await walletClient.writeContract({
          address: escrowAddr,
          abi: ESCROW_ABI,
          functionName: "purchase",
          account: address,
          chain: expectedChain,
          args: [signalId, notional, odds],
        });
        debug("[purchase-signal] tx:", hash);
        setTxHash(hash);
        await waitForTx(hash);
        return hash;
      } catch (err) {
        console.error("[purchase-signal] FAILED:", err);
        setError(humanizeError(err));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address]
  );

  return { purchase, loading, error, txHash };
}

/**
 * Probe whether depositWithPermit is usable on this network. Requires BOTH:
 *   1. Escrow.supportsFeature(DEPOSIT_WITH_PERMIT) returns true (V6+)
 *   2. USDC exposes EIP-2612 DOMAIN_SEPARATOR() (Circle USDC yes, MockUSDC no)
 *
 * Cached per (escrow, usdc) pair — both addresses are build-time constants
 * in practice, so one probe per page load is plenty.
 *
 * Returns { supported: false } if either gate fails. Failing safe is
 * important: a false positive would cause deposits to revert with
 * permit_unsupported_or_invalid at tx time, wasting gas.
 */
// Cache POSITIVE results only (per audit S1 + fresh-eyes review 2026-04-14).
// A transient RPC failure at load time would otherwise permanently disable
// the permit path for the session. Negative probes return without caching.
const _permitProbeCache = new Map<string, PermitProbeResult>();

interface PermitProbeResult {
  supported: boolean;
  usdcName?: string;
  usdcVersion?: string;
  reason?: string;
}

/**
 * Locally compute the EIP-712 DOMAIN_SEPARATOR for an EIP-2612 token and
 * return it as a bytes32 hex string. Must match the on-chain value exactly
 * or ECRECOVER inside permit() will return the wrong address.
 *
 * typeHash = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
 * domainSeparator = keccak256(abi.encode(typeHash, keccak256(name), keccak256(version), chainId, verifyingContract))
 */
async function computeExpectedDomainSeparator(
  name: string,
  version: string,
  chainId: number,
  verifyingContract: Hex,
): Promise<Hex> {
  const { keccak256: _keccak, toHex, encodeAbiParameters, stringToBytes } =
    await import("viem");
  const typeHash = _keccak(
    stringToBytes(
      "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)",
    ),
  );
  const nameHash = _keccak(stringToBytes(name));
  const versionHash = _keccak(stringToBytes(version));
  const encoded = encodeAbiParameters(
    [
      { type: "bytes32" },
      { type: "bytes32" },
      { type: "bytes32" },
      { type: "uint256" },
      { type: "address" },
    ],
    [typeHash, nameHash, versionHash, BigInt(chainId), verifyingContract],
  );
  return _keccak(encoded) as Hex;
  // toHex kept imported in case future versions need coercion; silence unused-var
  void toHex;
}

async function probePermitSupport(
  escrowAddr: Hex,
  usdcAddr: Hex,
  expectedChainId: number,
): Promise<PermitProbeResult> {
  const key = `${expectedChainId}:${escrowAddr.toLowerCase()}:${usdcAddr.toLowerCase()}`;
  const cached = _permitProbeCache.get(key);
  if (cached) return cached;

  const provider = getReadProvider();

  // Gate 1: Escrow supportsFeature(DEPOSIT_WITH_PERMIT).
  // Pre-V6 Escrow has no supportsFeature function; the call reverts and
  // we treat that as "not supported" (fall back to approve+deposit).
  try {
    const escrow = new ethers.Contract(
      escrowAddr,
      ["function supportsFeature(bytes32) view returns (bool)"],
      provider,
    );
    const hasPermit: boolean = await escrow.supportsFeature(getFeatureDepositWithPermitId());
    if (!hasPermit) {
      return { supported: false, reason: "escrow lacks DEPOSIT_WITH_PERMIT feature" };
    }
  } catch {
    return { supported: false, reason: "escrow supportsFeature() absent (pre-V6)" };
  }

  // Gate 2: USDC implements EIP-2612 permit AND the domain-separator we'd
  // sign against matches the on-chain value. This catches name/version
  // drift (Circle USDC on Base is version="2", not "1") before we prompt
  // the user to sign a useless permit.
  try {
    const usdc = new ethers.Contract(
      usdcAddr,
      [
        "function name() view returns (string)",
        "function version() view returns (string)",
        "function DOMAIN_SEPARATOR() view returns (bytes32)",
      ],
      provider,
    );
    const [name, onchainDS] = await Promise.all([
      usdc.name() as Promise<string>,
      usdc.DOMAIN_SEPARATOR() as Promise<string>,
    ]);
    if (!onchainDS || onchainDS === "0x" + "0".repeat(64)) {
      return { supported: false, reason: "usdc DOMAIN_SEPARATOR is zero" };
    }

    // version() is optional on-chain. Try it; if it fails, probe BOTH
    // "1" and "2" against the on-chain DS to discover the right value.
    // This is the only way to distinguish OZ's embedded version from
    // Circle FiatTokenV2's explicit "2" without trusting a stray RPC call.
    let version: string | undefined;
    try {
      const reported = (await (usdc.version() as Promise<string>)) || undefined;
      if (reported) version = reported;
    } catch {
      version = undefined;
    }

    const candidates = version ? [version] : ["1", "2"];
    let matched: string | undefined;
    const normalizedOnchain = onchainDS.toLowerCase();
    for (const v of candidates) {
      const expected = await computeExpectedDomainSeparator(
        name,
        v,
        expectedChainId,
        usdcAddr,
      );
      if (expected.toLowerCase() === normalizedOnchain) {
        matched = v;
        break;
      }
    }
    if (!matched) {
      return {
        supported: false,
        reason:
          "DOMAIN_SEPARATOR mismatch: signed domain would not recover the owner. " +
          `On-chain DS does not match name=${name} with version in [${candidates.join(", ")}] on chainId=${expectedChainId}`,
      };
    }

    const result: PermitProbeResult = { supported: true, usdcName: name, usdcVersion: matched };
    _permitProbeCache.set(key, result);
    return result;
  } catch (err) {
    return {
      supported: false,
      reason: `usdc lacks EIP-2612: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/**
 * Test-only helper: clears the module-level probe cache. Useful when
 * switching networks in a session or when a fresh upgrade just landed.
 */
export function _clearPermitProbeCache(): void {
  _permitProbeCache.clear();
}

export function useDepositEscrow() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsApproval, setNeedsApproval] = useState(false);
  const justApprovedRef = useRef(false);

  const deposit = useCallback(
    async (amount: bigint) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      try {
        const usdcAddr = ADDRESSES.usdc as Hex;
        const escrowAddr = ADDRESSES.escrow as Hex;

        // Pre-check balance via read provider
        const usdcRead = getUsdcContract(getReadProvider());
        const balance = await usdcRead.balanceOf(address);
        if (balance < amount) {
          throw new Error(`Insufficient USDC balance: have ${balance}, need ${amount}`);
        }

        // Fast path: if both Escrow V6 and a permit-capable USDC are
        // present, sign an EIP-2612 permit and call depositWithPermit.
        // One on-chain tx instead of two (approve + deposit), so half the
        // gas and for Coinbase Smart Wallet users, one popup instead of
        // two. Falls through to the legacy path on any failure.
        if (!justApprovedRef.current) {
          const chainId = await walletClient.getChainId();
          const probe = await probePermitSupport(escrowAddr, usdcAddr, chainId);
          if (probe.supported) {
            try {
              // Deadline: 20 minutes from now. Longer than a typical
              // wallet-signing flow; short enough that a stolen permit
              // can't linger.
              const deadline = BigInt(Math.floor(Date.now() / 1000) + 20 * 60);
              const usdcReadContract = new ethers.Contract(
                usdcAddr,
                [
                  "function nonces(address) view returns (uint256)",
                ],
                getReadProvider(),
              );
              const nonce: bigint = await usdcReadContract.nonces(address);

              debug("[escrow-deposit] signing permit", { amount: amount.toString(), deadline: deadline.toString() });
              // Probe has verified usdcVersion matches the on-chain
              // DOMAIN_SEPARATOR, so we don't fall back to "1" — use
              // whatever the probe confirmed or abort via the outer
              // try/catch fallback path.
              if (!probe.usdcVersion) {
                throw new Error("probe returned supported=true without a verified version");
              }
              const signature = await walletClient.signTypedData({
                account: address,
                domain: {
                  name: probe.usdcName ?? "USD Coin",
                  version: probe.usdcVersion,
                  chainId,
                  verifyingContract: usdcAddr,
                },
                types: {
                  Permit: [
                    { name: "owner", type: "address" },
                    { name: "spender", type: "address" },
                    { name: "value", type: "uint256" },
                    { name: "nonce", type: "uint256" },
                    { name: "deadline", type: "uint256" },
                  ],
                },
                primaryType: "Permit",
                message: {
                  owner: address,
                  spender: escrowAddr,
                  value: amount,
                  nonce,
                  deadline,
                },
              });

              // Split 65-byte signature into (v, r, s). Normalize v:
              // some wallets (older Ledger firmware, certain WalletConnect
              // paths) return v in {0, 1}; EIP-2612 permit expects
              // {27, 28}. An unnormalized v makes ECRECOVER return a
              // different address and permit() reverts.
              const sigHex = signature.startsWith("0x") ? signature.slice(2) : signature;
              const r = ("0x" + sigHex.slice(0, 64)) as Hex;
              const s = ("0x" + sigHex.slice(64, 128)) as Hex;
              let v = parseInt(sigHex.slice(128, 130), 16);
              if (v < 27) v += 27;

              debug("[escrow-deposit] depositWithPermit", amount.toString());
              const depositHash = await walletClient.writeContract({
                address: escrowAddr,
                abi: ESCROW_ABI,
                functionName: "depositWithPermit",
                account: address,
                chain: expectedChain,
                args: [amount, deadline, v, r, s],
              });
              debug("[escrow-deposit] depositWithPermit tx:", depositHash);
              await waitForTx(depositHash);
              setNeedsApproval(false);
              return depositHash;
            } catch (permitErr) {
              // If the user explicitly rejected the typed-data signature,
              // do NOT fall through to the legacy approve+deposit flow —
              // that would hit them with a second popup they didn't ask
              // for. Re-throw so the caller sees the rejection and stops.
              // Codex-audit MEDIUM-3 (2026-04-14).
              const msg = permitErr instanceof Error ? permitErr.message : String(permitErr);
              const code = (permitErr as { code?: number })?.code;
              const name = (permitErr as { name?: string })?.name;
              if (
                code === 4001 ||
                name === "UserRejectedRequestError" ||
                /user rejected|user denied|ACTION_REJECTED/i.test(msg)
              ) {
                throw permitErr;
              }
              // Structural failure (USDC doesn't actually support permit
              // despite the probe, wallet refused typed-data, etc.) →
              // fall through to approve+deposit.
              console.warn("[escrow-deposit] permit path structural failure, falling back:", permitErr);
            }
          }
        }

        // Skip allowance check if we just approved (RPC may lag behind on-chain state)
        if (!justApprovedRef.current) {
          const allowance: bigint = await usdcRead.allowance(address, escrowAddr);
          if (allowance < amount) {
            // Coinbase Smart Wallet can only handle one popup per user action.
            // Do ONLY the approve here, then return. Caller clicks again for deposit.
            const MAX_UINT256 = 2n ** 256n - 1n;
            debug("[escrow-deposit] approving (max allowance)");
            const approveHash = await walletClient.writeContract({
              address: usdcAddr,
              abi: ERC20_ABI,
              functionName: "approve",
              account: address,
              chain: expectedChain,
              args: [escrowAddr, MAX_UINT256],
            });
            debug("[escrow-deposit] approve tx:", approveHash);
            await waitForTx(approveHash);
            setNeedsApproval(false);
            justApprovedRef.current = true;
            return "approved" as const;
          }
        }

        // Deposit into escrow (single popup)
        justApprovedRef.current = false;
        debug("[escrow-deposit] depositing", amount.toString());
        const depositHash = await walletClient.writeContract({
          address: escrowAddr,
          abi: ESCROW_ABI,
          functionName: "deposit",
          account: address,
          chain: expectedChain,
          args: [amount],
        });
        debug("[escrow-deposit] deposit tx:", depositHash);
        await waitForTx(depositHash);

        return depositHash;
      } catch (err) {
        console.error("[escrow-deposit] FAILED:", err);
        justApprovedRef.current = false;
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Deposit failed: ${msg}`);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address]
  );

  // Check approval state on mount and after deposit
  const checkApproval = useCallback(async (amount: bigint) => {
    if (!address) return;
    try {
      const usdcRead = getUsdcContract(getReadProvider());
      const escrowAddr = ADDRESSES.escrow as Hex;
      const allowance: bigint = await usdcRead.allowance(address, escrowAddr);
      setNeedsApproval(allowance < amount);
    } catch { /* ignore */ }
  }, [address]);

  return { deposit, loading, error, needsApproval, checkApproval };
}

export function useDepositCollateral() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsApproval, setNeedsApproval] = useState(false);
  const justApprovedRef = useRef(false);

  const deposit = useCallback(
    async (amount: bigint) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      try {
        const usdcAddr = ADDRESSES.usdc as Hex;
        const collateralAddr = ADDRESSES.collateral as Hex;

        // Pre-check balance via read provider
        const usdcRead = getUsdcContract(getReadProvider());
        const balance = await usdcRead.balanceOf(address);
        if (balance < amount) {
          throw new Error(`Insufficient USDC balance: have ${balance}, need ${amount}`);
        }

        // Skip allowance check if we just approved (RPC may lag behind on-chain state)
        if (!justApprovedRef.current) {
          const allowance: bigint = await usdcRead.allowance(address, collateralAddr);
          if (allowance < amount) {
            // Coinbase Smart Wallet can only handle one popup per user action.
            // Do ONLY the approve here, then return. Caller clicks again for deposit.
            const MAX_UINT256 = 2n ** 256n - 1n;
            debug("[collateral-deposit] approving (max allowance)");
            const approveHash = await walletClient.writeContract({
              address: usdcAddr,
              abi: ERC20_ABI,
              functionName: "approve",
              account: address,
              chain: expectedChain,
              args: [collateralAddr, MAX_UINT256],
            });
            debug("[collateral-deposit] approve tx:", approveHash);
            await waitForTx(approveHash);
            setNeedsApproval(false);
            justApprovedRef.current = true;
            return "approved" as const;
          }
        }

        // Deposit into collateral (single popup)
        justApprovedRef.current = false;
        debug("[collateral-deposit] depositing", amount.toString());
        const depositHash = await walletClient.writeContract({
          address: collateralAddr,
          abi: COLLATERAL_ABI,
          functionName: "deposit",
          account: address,
          chain: expectedChain,
          args: [amount],
        });
        debug("[collateral-deposit] deposit tx:", depositHash);
        await waitForTx(depositHash);

        return depositHash;
      } catch (err) {
        console.error("[collateral-deposit] FAILED:", err);
        justApprovedRef.current = false;
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Deposit failed: ${msg}`);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address]
  );

  const checkApproval = useCallback(async (amount: bigint) => {
    if (!address) return;
    try {
      const usdcRead = getUsdcContract(getReadProvider());
      const collateralAddr = ADDRESSES.collateral as Hex;
      const allowance: bigint = await usdcRead.allowance(address, collateralAddr);
      setNeedsApproval(allowance < amount);
    } catch { /* ignore */ }
  }, [address]);

  return { deposit, loading, error, needsApproval, checkApproval };
}

// ---------------------------------------------------------------------------
// Withdraw hooks
// ---------------------------------------------------------------------------

export function useWithdrawEscrow() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const withdraw = useCallback(
    async (amount: bigint) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      try {
        const escrowAddr = ADDRESSES.escrow as Hex;
        debug("[escrow-withdraw] withdrawing", amount.toString());
        const hash = await walletClient.writeContract({
          address: escrowAddr,
          abi: ESCROW_ABI,
          functionName: "withdraw",
          account: address,
          chain: expectedChain,
          args: [amount],
          gas: 200_000n,
        });
        debug("[escrow-withdraw] tx:", hash);
        await waitForTx(hash);
        return hash;
      } catch (err) {
        console.error("[escrow-withdraw] FAILED:", err);
        setError(humanizeError(err, "Withdraw failed"));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address]
  );

  return { withdraw, loading, error };
}

export function useWithdrawCollateral() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const withdraw = useCallback(
    async (amount: bigint) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      try {
        const collateralAddr = ADDRESSES.collateral as Hex;
        debug("[collateral-withdraw] withdrawing", amount.toString());
        const hash = await walletClient.writeContract({
          address: collateralAddr,
          abi: COLLATERAL_ABI,
          functionName: "withdraw",
          account: address,
          chain: expectedChain,
          args: [amount],
          gas: 200_000n,
        });
        debug("[collateral-withdraw] tx:", hash);
        await waitForTx(hash);
        return hash;
      } catch (err) {
        console.error("[collateral-withdraw] FAILED:", err);
        setError(humanizeError(err, "Withdraw failed"));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address]
  );

  return { withdraw, loading, error };
}

// ---------------------------------------------------------------------------
// Early exit hook — either party can trigger before a full audit batch
// ---------------------------------------------------------------------------

export function useEarlyExit() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);

  const earlyExit = useCallback(
    async (genius: string, idiot: string, purchaseIds: bigint[]) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      if (purchaseIds.length === 0) throw new Error("No purchases to settle");
      // Contract enforces 1-9 purchases per early-exit call (must be <
      // MIN_BATCH_SIZE=10). Larger batches go through the natural-quorum path.
      if (purchaseIds.length > 9) {
        throw new Error(
          `Too many purchases (${purchaseIds.length}); early-exit batches max 9. Wait for natural settlement at 10+.`,
        );
      }
      // ascending sort required by Audit._verifyAllOutcomesFinalized
      const sortedIds = [...purchaseIds].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
      setLoading(true);
      setError(null);
      setTxHash(null);
      try {
        const auditAddr = ADDRESSES.audit as Hex;
        debug("[early-exit] triggering", genius, idiot, "ids:", sortedIds);
        const hash = await walletClient.writeContract({
          address: auditAddr,
          abi: AUDIT_VIEM_ABI,
          functionName: "earlyExit",
          account: address,
          chain: expectedChain,
          args: [genius as Hex, idiot as Hex, sortedIds],
        });
        debug("[early-exit] tx:", hash);
        setTxHash(hash);
        await waitForTx(hash);
        return hash;
      } catch (err) {
        console.error("[early-exit] FAILED:", err);
        setError(humanizeError(err, "Early exit failed"));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address],
  );

  return { earlyExit, loading, error, txHash };
}

/**
 * Fetch the (genius, idiot) pair's purchase IDs that are RESOLVED (outcome
 * != Pending) but NOT yet AUDITED. These are the IDs eligible for the
 * caller-initiated early-exit path. Sorted ascending. Capped at 9 (the
 * contract's per-call max for early-exit batches).
 */
export async function fetchEarlyExitableIds(
  genius: string,
  idiot: string,
): Promise<bigint[]> {
  const provider = getReadProvider();
  const account = new ethers.Contract(ADDRESSES.account!, ACCOUNT_ABI, provider);
  const allIds: bigint[] = (await account.getPairPurchaseIds(genius, idiot)).map(
    (x: ethers.BigNumberish) => BigInt(x),
  );
  if (allIds.length === 0) return [];
  // Concurrent audited+outcome checks. Outcome enum: 0=Pending, 1=Win, 2=Loss, etc.
  // Pending (0) means not yet resolved; eligible IDs need outcome != 0.
  const checks = await Promise.all(
    allIds.map(async (pid) => {
      const [audited, outcomeRaw] = await Promise.all([
        account.isPurchaseAudited(pid),
        account.getOutcome(genius, idiot, pid),
      ]);
      const outcome = Number(outcomeRaw);
      return { pid, audited: Boolean(audited), resolved: outcome !== 0 };
    }),
  );
  return checks
    .filter((c) => !c.audited && c.resolved)
    .map((c) => c.pid)
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
    .slice(0, 9);
}

// ---------------------------------------------------------------------------
// Void (cancel) a signal
// ---------------------------------------------------------------------------

export function useCancelSignal() {
  const { data: walletClient } = useWalletClient();
  const { address } = useAccount();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);

  const cancelSignal = useCallback(
    async (signalId: bigint) => {
      if (!walletClient || !address) throw new Error("Wallet not connected");
      assertCorrectChain(walletClient);
      setLoading(true);
      setError(null);
      setTxHash(null);
      try {
        const hash = await walletClient.writeContract({
          address: ADDRESSES.signalCommitment as Hex,
          abi: SIGNAL_COMMITMENT_VIEM_ABI,
          functionName: "cancelSignal",
          account: address,
          chain: expectedChain,
          args: [signalId],
        });
        setTxHash(hash);
        await waitForTx(hash);
        return hash;
      } catch (err) {
        const msg = humanizeError(err, "Failed to cancel signal");
        setError(msg);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [walletClient, address],
  );

  return { cancelSignal, loading, error, txHash };
}

// ---------------------------------------------------------------------------
// Fetch purchases for a signal (how much notional has been taken)
// ---------------------------------------------------------------------------

export function useSignalNotionalFilled(signalId: string | undefined) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["signal-notional-filled", signalId ?? "none"] as const,
    [signalId],
  );

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      try {
        const escrow = getEscrowContract(getReadProvider());
        const val = await escrow.signalNotionalFilled(signalId!);
        return BigInt(val);
      } catch {
        // Contract may not have this signal yet — silent 0n
        return 0n;
      }
    },
    enabled: Boolean(signalId),
    staleTime: 15_000,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey }),
    [queryClient, queryKey],
  );

  return {
    filled: (query.data ?? 0n) as bigint,
    loading: query.isFetching,
    refresh,
  };
}

export function useSignalPurchases(signalId: string | undefined) {
  type PurchaseRow = { purchaseId: bigint; notional: bigint; buyer: string; outcome: number };

  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["signal-purchases", signalId ?? "none"] as const,
    [signalId],
  );

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      try {
        const escrow = getEscrowContract(getReadProvider());
        const purchaseIds: bigint[] = await escrow.getPurchasesBySignal(signalId!);
        const results: PurchaseRow[] = [];
        let total = 0n;
        for (const pid of purchaseIds) {
          const p = await escrow.getPurchase(pid);
          const notional = BigInt(p.notional ?? 0);
          results.push({
            purchaseId: pid,
            notional,
            buyer: String(p.idiot ?? ""),
            outcome: Number(p.outcome ?? 0),
          });
          total += notional;
        }
        return { purchases: results, totalNotional: total };
      } catch {
        // Contract may not have this signal — silent empty
        return { purchases: [] as PurchaseRow[], totalNotional: 0n };
      }
    },
    enabled: Boolean(signalId),
    staleTime: 15_000,
  });

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey }),
    [queryClient, queryKey],
  );

  const data = query.data;
  return {
    purchases: data?.purchases ?? [],
    totalNotional: (data?.totalNotional ?? 0n) as bigint,
    loading: query.isFetching,
    refresh,
  };
}
