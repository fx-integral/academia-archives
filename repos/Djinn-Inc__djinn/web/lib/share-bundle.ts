/**
 * Build the encrypted-share bundle that the genius client fans out to every
 * OV signer (Phase 3 of share recovery, project_share_recovery_design_2026_05_03.md).
 *
 * For each OV signer with a published x25519 pubkey:
 *   - Generate one Shamir share of the secret (key + index).
 *   - SealedBox-encrypt the share's y-coordinate to that signer's pubkey.
 *   - Pack into a per-target bundle entry.
 *
 * The SAME bundle is POSTed to every validator URL. Each validator finds its
 * own entry by matching its signer EOA, decrypts via pynacl SealedBox, and
 * stores the rest as forwarding blobs that peers serve via /v1/share-recovery.
 */

import { splitSecret, type ShamirShare } from "@/lib/crypto";
import {
  bigIntToBytes32,
  bytesToHex,
  isZeroPubkey,
  sealedBoxEncrypt,
} from "@/lib/share-crypto";
import type { OVValidatorPubkey } from "@/lib/encryption-pubkeys";

export interface ShareBundleEntry {
  target_address: string; // checksummed validator signer EOA
  share_x: number;
  share_ciphertext: string; // hex-encoded SealedBox ciphertext
  index_ciphertext: string; // hex-encoded SealedBox ciphertext (or "" if no index_y)
}

export interface ShareBundle {
  signal_id: string;
  genius_address: string;
  shamir_threshold: number;
  bundle: ShareBundleEntry[];
}

export interface BuildBundleArgs {
  signalId: string;
  geniusAddress: string;
  keyBigInt: bigint; // the secret to Shamir-split (e.g. AES key)
  indexBigInt: bigint; // 1-indexed real signal index
  validators: OVValidatorPubkey[]; // OV signer set with their pubkeys
  shamirMin: number; // SHAMIR_MIN floor (default 2)
  shamirMax: number; // SHAMIR_MAX cap (default 7)
}

export interface BuildBundleResult {
  bundle: ShareBundle;
  encryptableValidators: OVValidatorPubkey[]; // those with non-zero pubkey, used in the bundle
  skippedValidators: OVValidatorPubkey[]; // those with zero pubkey (skipped, retry on later signal)
  effectiveThreshold: number;
  nShares: number;
}

/**
 * Build the encrypted bundle for a single signal.
 *
 * Validators with a zero pubkey on chain are skipped — they haven't yet
 * called setEncryptionPubkey. The bundle excludes them; if/when they
 * publish a pubkey, the next signal-create will include them. (Stuck
 * historical batches are not retroactively healed; that's the
 * "going-forward only" decision in the locked design memo.)
 */
export function buildShareBundle(args: BuildBundleArgs): BuildBundleResult {
  const { signalId, geniusAddress, keyBigInt, indexBigInt, validators, shamirMin, shamirMax } = args;

  const encryptable = validators.filter((v) => !isZeroPubkey(v.pubkey));
  const skipped = validators.filter((v) => isZeroPubkey(v.pubkey));

  const nShares = encryptable.length;
  if (nShares < shamirMin) {
    throw new Error(
      `Cannot build bundle: only ${nShares} validator(s) have published encryption pubkeys, ` +
        `below SHAMIR_MIN=${shamirMin}. Wait for more validators to register or fall back to legacy fan-out.`,
    );
  }

  const effectiveThreshold = Math.min(shamirMax, Math.max(shamirMin, Math.ceil((nShares * 2) / 3)));

  const keyShares: ShamirShare[] = splitSecret(keyBigInt, nShares, effectiveThreshold);
  const indexShares: ShamirShare[] = splitSecret(indexBigInt, nShares, effectiveThreshold);

  const entries: ShareBundleEntry[] = encryptable.map((v, i) => {
    const keyShareBytes = bigIntToBytes32(keyShares[i].y);
    const indexShareBytes = bigIntToBytes32(indexShares[i].y);
    const keyCiphertext = sealedBoxEncrypt(v.pubkey, keyShareBytes);
    const indexCiphertext = sealedBoxEncrypt(v.pubkey, indexShareBytes);
    return {
      target_address: v.address,
      share_x: keyShares[i].x,
      share_ciphertext: bytesToHex(keyCiphertext),
      index_ciphertext: bytesToHex(indexCiphertext),
    };
  });

  return {
    bundle: {
      signal_id: signalId,
      genius_address: geniusAddress,
      shamir_threshold: effectiveThreshold,
      bundle: entries,
    },
    encryptableValidators: encryptable,
    skippedValidators: skipped,
    effectiveThreshold,
    nShares,
  };
}
