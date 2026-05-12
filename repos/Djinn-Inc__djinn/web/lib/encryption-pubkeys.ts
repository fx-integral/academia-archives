/**
 * Read OV.encryptionPubkey() + OV.supportsFeature() for share recovery.
 *
 * The genius client uses these to decide whether to use the new
 * encrypted-bundle fan-out path (Phase 3 of share recovery) or fall
 * back to the legacy plaintext-share path. See
 * project_share_recovery_design_2026_05_03.md.
 */

import { ethers } from "ethers";
import { getReadProvider } from "@/lib/hooks";

const OV_SHARE_RECOVERY_ABI = [
  "function getValidators() view returns (address[])",
  "function encryptionPubkey(address) view returns (bytes32)",
  "function supportsFeature(bytes32) view returns (bool)",
];

const FEATURE_SHARE_RECOVERY = ethers.id("SHARE_RECOVERY");

export interface OVValidatorPubkey {
  address: string; // checksummed signer EOA
  pubkey: Uint8Array; // 32 bytes; all-zero means not yet published
}

let _supportsCache: { value: boolean; ts: number } | null = null;
const SUPPORTS_CACHE_MS = 5 * 60 * 1000;

let _validatorPubkeysCache: { entries: OVValidatorPubkey[]; ts: number } | null = null;
const PUBKEY_CACHE_MS = 60 * 1000;

function getOVAddress(): string {
  const addr = process.env.NEXT_PUBLIC_OUTCOME_VOTING_ADDRESS;
  if (!addr || addr === "0x0000000000000000000000000000000000000000") {
    throw new Error("NEXT_PUBLIC_OUTCOME_VOTING_ADDRESS not configured");
  }
  return addr;
}

function getOVContract(provider?: ethers.Provider): ethers.Contract {
  return new ethers.Contract(getOVAddress(), OV_SHARE_RECOVERY_ABI, provider ?? getReadProvider());
}

/**
 * Returns true if the live OV impl exposes setEncryptionPubkey + supportsFeature.
 * Falsy if the proxy is on an older impl (legacy path), or if the call reverts.
 * Cached for 5 minutes — feature support flips at most once per upgrade and
 * rate-limiting RPC calls is courtesy.
 */
export async function ovSupportsShareRecovery(): Promise<boolean> {
  if (_supportsCache && Date.now() - _supportsCache.ts < SUPPORTS_CACHE_MS) {
    return _supportsCache.value;
  }
  try {
    const ov = getOVContract();
    const value = await ov.supportsFeature(FEATURE_SHARE_RECOVERY);
    _supportsCache = { value: !!value, ts: Date.now() };
    return _supportsCache.value;
  } catch {
    _supportsCache = { value: false, ts: Date.now() };
    return false;
  }
}

/**
 * Read the full OV signer set + their published encryption pubkeys from chain.
 * Returns one entry per validator; the `pubkey` field is all-zero if the
 * validator has not yet called setEncryptionPubkey.
 *
 * Cached for 60s. The genius client invalidates on signal-create error
 * (so a recently-rotated pubkey is picked up on retry).
 */
export async function fetchOVValidatorPubkeys(): Promise<OVValidatorPubkey[]> {
  if (_validatorPubkeysCache && Date.now() - _validatorPubkeysCache.ts < PUBKEY_CACHE_MS) {
    return _validatorPubkeysCache.entries;
  }
  const ov = getOVContract();
  const validators: string[] = await ov.getValidators();
  const entries = await Promise.all(
    validators.map(async (addr: string) => {
      const checksum = ethers.getAddress(addr);
      try {
        const hex: string = await ov.encryptionPubkey(checksum);
        return { address: checksum, pubkey: hexToBytes(hex) };
      } catch {
        return { address: checksum, pubkey: new Uint8Array(32) };
      }
    }),
  );
  _validatorPubkeysCache = { entries, ts: Date.now() };
  return entries;
}

/**
 * Force-invalidate the validator-pubkey cache. Call when retrying a fan-out
 * after a recent storeShareBundle 503 — the validator may have just published
 * a fresh pubkey.
 */
export function invalidateValidatorPubkeyCache(): void {
  _validatorPubkeysCache = null;
}

function hexToBytes(hex: string): Uint8Array {
  const cleaned = hex.startsWith("0x") || hex.startsWith("0X") ? hex.slice(2) : hex;
  if (cleaned.length !== 64) {
    throw new Error(`expected 64 hex chars, got ${cleaned.length}`);
  }
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}
