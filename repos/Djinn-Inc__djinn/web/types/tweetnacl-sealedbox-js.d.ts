declare module "tweetnacl-sealedbox-js" {
  /**
   * NaCl SealedBox: anonymous, ephemeral-key encryption to a recipient's
   * x25519 pubkey. Compatible with libsodium's crypto_box_seal /
   * crypto_box_seal_open. See
   * project_share_recovery_design_2026_05_03.md for usage.
   */
  export function seal(message: Uint8Array, recipientPublicKey: Uint8Array): Uint8Array;
  export function open(
    ciphertext: Uint8Array,
    recipientPublicKey: Uint8Array,
    recipientSecretKey: Uint8Array,
  ): Uint8Array | null;
  export const overheadLength: number;
  const _default: {
    seal: typeof seal;
    open: typeof open;
  };
  export default _default;
}
