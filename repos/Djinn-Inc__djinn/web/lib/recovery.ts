/**
 * Key recovery: encrypt signal data to a signature-derived AES key and
 * store/retrieve it from the KeyRecovery contract on-chain.
 *
 * Flow:
 *   1. User signs a deterministic message "Djinn Key Recovery v1"
 *   2. SHA-256 hash of the signature => 32-byte AES-256 key
 *   3. Signal data array is JSON-serialized and AES-GCM encrypted
 *   4. Encrypted blob is stored on-chain via KeyRecovery.storeRecoveryBlob()
 *   5. Recovery: sign same message => same key => decrypt blob from chain
 *
 * Security: The key is derived from a wallet signature that only the private
 * key holder can produce. Most wallets use RFC 6979 (deterministic k), so the
 * same message always yields the same signature and thus the same AES key.
 */

import { encrypt, decrypt, toHex, fromHex, deriveMasterSeedTyped } from "./crypto";
import type { SignTypedDataParams } from "./crypto";
import { getKeyRecoveryContract, ADDRESSES } from "./contracts";
import { getReadProvider } from "./hooks";
import type { SavedSignalData } from "./hooks/useSettledSignals";
import type { PurchasedSignalData } from "./preferences";

const RECOVERY_SIGN_MESSAGE = "Djinn Key Recovery v1";
const MAX_BLOB_SIZE = 4096;

// ---- Types ----

interface RecoveryBlobPayloadV1 {
  version: 1;
  signals: SavedSignalData[];
}

interface RecoveryBlobPayloadV2 {
  version: 2;
  signals: SavedSignalData[];
  purchases: PurchasedSignalData[];
}

type RecoveryBlobPayload = RecoveryBlobPayloadV1 | RecoveryBlobPayloadV2;

export interface RecoveryResult {
  signals: SavedSignalData[];
  purchases: PurchasedSignalData[];
}

// ---- Key Derivation ----

export async function deriveRecoveryKey(signature: string): Promise<Uint8Array> {
  const sigBytes = fromHex(signature.replace(/^0x/, ""));
  // Use Buffer.from on Node (realm-stable across jsdom env) and fall
  // back to Uint8Array.from in the browser. See lib/crypto.ts
  // toArrayBuffer for the full rationale.
  let buf: ArrayBuffer;
  if (typeof Buffer !== "undefined" && Buffer.from) {
    const b = Buffer.from(sigBytes);
    buf = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
  } else {
    buf = Uint8Array.from(sigBytes).buffer as ArrayBuffer;
  }
  const hashBuffer = await crypto.subtle.digest("SHA-256", buf);
  return new Uint8Array(hashBuffer);
}

// ---- Encrypt / Decrypt ----

export async function encryptRecoveryBlob(
  signals: SavedSignalData[],
  recoveryKey: Uint8Array,
  purchases?: PurchasedSignalData[],
): Promise<Uint8Array> {
  const payload: RecoveryBlobPayload =
    purchases && purchases.length > 0
      ? { version: 2, signals, purchases }
      : { version: 1, signals };
  const plaintext = JSON.stringify(payload);
  const { ciphertext, iv } = await encrypt(plaintext, recoveryKey);
  return new TextEncoder().encode(`${iv}:${ciphertext}`);
}

export async function decryptRecoveryBlob(
  blob: Uint8Array,
  recoveryKey: Uint8Array,
): Promise<RecoveryResult> {
  const packed = new TextDecoder().decode(blob);
  const colonIdx = packed.indexOf(":");
  if (colonIdx < 0) {
    throw new Error(
      "Recovery blob is corrupted (invalid format). " +
      "This may happen if the blob was truncated during storage. " +
      "Your on-chain data (purchases, settlements) is unaffected."
    );
  }
  const iv = packed.slice(0, colonIdx);
  const ciphertext = packed.slice(colonIdx + 1);

  let json: string;
  try {
    json = await decrypt(ciphertext, iv, recoveryKey);
  } catch {
    throw new Error(
      "Could not decrypt recovery blob. This usually means the blob was stored " +
      "with a different wallet or was corrupted. Your on-chain data is unaffected."
    );
  }

  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(json);
  } catch {
    throw new Error(
      "Recovery blob decrypted but contains invalid data. " +
      "Your on-chain data (purchases, settlements) is unaffected."
    );
  }

  if (raw?.version !== 1 && raw?.version !== 2) {
    throw new Error(
      `Unsupported recovery blob version: ${raw?.version}. ` +
      "You may need a newer version of the app to read this backup."
    );
  }

  const payload = raw as unknown as RecoveryBlobPayload;

  // Graceful degradation: filter out malformed entries instead of failing entirely
  const signals = Array.isArray(payload.signals)
    ? payload.signals.filter(
        (s): s is SavedSignalData => typeof s === "object" && s !== null && "signalId" in s
      )
    : [];

  const purchases =
    payload.version === 2 && Array.isArray(payload.purchases)
      ? payload.purchases.filter(
          (p): p is PurchasedSignalData => typeof p === "object" && p !== null && "signalId" in p
        )
      : [];

  return { signals, purchases };
}

// ---- On-Chain Read (view, no gas) ----

export async function readRecoveryBlobFromChain(
  userAddress: string,
): Promise<Uint8Array | null> {
  if (ADDRESSES.keyRecovery === "0x0000000000000000000000000000000000000000") {
    return null;
  }
  const contract = getKeyRecoveryContract(getReadProvider());
  const blob: string = await contract.getRecoveryBlob(userAddress);
  if (!blob || blob === "0x" || blob.length <= 2) return null;
  return fromHex(blob.replace(/^0x/, ""));
}

// ---- On-Chain Write ----

const KEY_RECOVERY_VIEM_ABI = [
  {
    type: "function" as const,
    name: "storeRecoveryBlob" as const,
    inputs: [{ name: "blob" as const, type: "bytes" as const }],
    outputs: [],
    stateMutability: "nonpayable" as const,
  },
] as const;

export async function storeRecoveryBlobOnChain(
  walletClient: { writeContract: (args: any) => Promise<`0x${string}`>; account?: { address: `0x${string}` }; chain?: { id: number } },
  blob: Uint8Array,
  waitForTxFn: (hash: `0x${string}`) => Promise<void>,
): Promise<`0x${string}`> {
  if (blob.length === 0) throw new Error("Recovery blob is empty");
  if (blob.length > MAX_BLOB_SIZE) {
    throw new Error(
      `Recovery blob too large: ${blob.length} bytes (max ${MAX_BLOB_SIZE}). ` +
      `Consider pruning old signals.`,
    );
  }

  const hash = await walletClient.writeContract({
    address: ADDRESSES.keyRecovery as `0x${string}`,
    abi: KEY_RECOVERY_VIEM_ABI,
    functionName: "storeRecoveryBlob",
    account: walletClient.account?.address,
    chain: walletClient.chain,
    args: [`0x${toHex(blob)}`],
  });

  await waitForTxFn(hash);
  return hash;
}

// ---- High-Level Orchestration ----

export async function storeRecovery(
  signTypedDataFn: (params: SignTypedDataParams) => Promise<string>,
  walletClient: { writeContract: (args: any) => Promise<`0x${string}`> },
  signals: SavedSignalData[],
  waitForTxFn: (hash: `0x${string}`) => Promise<void>,
  purchases?: PurchasedSignalData[],
): Promise<`0x${string}`> {
  if (signals.length === 0 && (!purchases || purchases.length === 0)) {
    throw new Error("No data to store for recovery");
  }
  if (ADDRESSES.keyRecovery === "0x0000000000000000000000000000000000000000") {
    throw new Error("KeyRecovery contract not configured");
  }

  const masterSeed = await deriveMasterSeedTyped(signTypedDataFn);
  const blob = await encryptRecoveryBlob(signals, masterSeed, purchases);
  const hash = await storeRecoveryBlobOnChain(walletClient, blob, waitForTxFn);
  // storeRecoveryBlobOnChain doesn't know the owner address, so callers that
  // want debounce must call markRecoveryStored themselves. maybeStoreRecovery
  // below handles that automatically.
  return hash;
}

// ---- Debounce helpers ----
//
// A recovery-blob on-chain store is a full wallet transaction. In rapid-burst
// flows (a genius publishing 3 signals back-to-back, or an idiot purchasing
// several signals in a minute) every event previously fired its own popup
// plus its own gas spend. localStorage is the primary store; the on-chain
// blob is a disaster-recovery snapshot and tolerates short staleness.
//
// `maybeStoreRecovery` checks the caller's last-stored timestamp and skips
// the on-chain write when the previous store was recent. The write still
// happens, just less often — losing at most `DEFAULT_MIN_INTERVAL_MS` of
// state between localStorage and the chain.

const RECOVERY_LAST_STORED_KEY = (address: string) =>
  `djinn-recovery-last-stored:${address.toLowerCase()}`;

const DEFAULT_MIN_INTERVAL_MS = 120_000; // 2 minutes

export function getLastRecoveryStoreMs(address: string): number | null {
  if (typeof window === "undefined" || !address) return null;
  try {
    const raw = window.localStorage.getItem(RECOVERY_LAST_STORED_KEY(address));
    if (!raw) return null;
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) return null;
    // Reject timestamps far in the future — an XSS attacker on another djinn.gg
    // subdomain could otherwise set `now + 10 years` and skip the on-chain
    // store forever. A one-day ceiling still tolerates reasonable clock skew.
    const maxFuture = Date.now() + 86_400_000;
    if (n > maxFuture) return null;
    return n;
  } catch {
    return null;
  }
}

export function markRecoveryStored(address: string, now: number = Date.now()): void {
  if (typeof window === "undefined" || !address) return;
  try {
    window.localStorage.setItem(RECOVERY_LAST_STORED_KEY(address), String(now));
  } catch {
    // localStorage write failures are non-fatal; the next call re-tries.
  }
}

export function shouldStoreRecoveryNow(
  address: string,
  minIntervalMs: number = DEFAULT_MIN_INTERVAL_MS,
  now: number = Date.now(),
): boolean {
  const last = getLastRecoveryStoreMs(address);
  if (last === null) return true;
  return now - last >= minIntervalMs;
}

/**
 * Like storeRecovery, but skips the on-chain write if this address stored
 * within the last `minIntervalMs`. Returns the tx hash when a store happens,
 * or `null` when the call was skipped. Safe to fire-and-forget from purchase
 * flows — the caller can ignore the return value.
 *
 * `force: true` bypasses the debounce (for explicit "backup now" buttons).
 */
export async function maybeStoreRecovery(
  ownerAddress: string,
  signTypedDataFn: (params: SignTypedDataParams) => Promise<string>,
  walletClient: { writeContract: (args: any) => Promise<`0x${string}`>; account?: { address: `0x${string}` } },
  signals: SavedSignalData[],
  waitForTxFn: (hash: `0x${string}`) => Promise<void>,
  purchases?: PurchasedSignalData[],
  options?: { force?: boolean; minIntervalMs?: number },
): Promise<`0x${string}` | null> {
  const force = options?.force === true;
  const minInterval = options?.minIntervalMs ?? DEFAULT_MIN_INTERVAL_MS;

  // The debounce key is ownerAddress; the signer is walletClient.account.
  // If those drift (user switched wallets between prop capture and await),
  // silently bailing is safer than marking the wrong debounce slot — which
  // would make the true owner's next backup get skipped.
  const signer = walletClient.account?.address;
  if (signer && signer.toLowerCase() !== ownerAddress.toLowerCase()) {
    return null;
  }

  if (!force && !shouldStoreRecoveryNow(ownerAddress, minInterval)) {
    return null;
  }
  const hash = await storeRecovery(
    signTypedDataFn, walletClient, signals, waitForTxFn, purchases,
  );
  markRecoveryStored(ownerAddress);
  return hash;
}

export async function loadRecovery(
  userAddress: string,
  signTypedDataFn: (params: SignTypedDataParams) => Promise<string>,
): Promise<RecoveryResult | null> {
  const blob = await readRecoveryBlobFromChain(userAddress);
  if (!blob) return null;

  const masterSeed = await deriveMasterSeedTyped(signTypedDataFn);
  return decryptRecoveryBlob(blob, masterSeed);
}
