import { ethers } from "ethers";
import { formatUsdc } from "./types";

// EIP-55 checksum the address and return null if it is not a valid 20-byte
// hex. Used by the public Genius profile route to validate an address taken
// straight from the URL (params.address) before we try to look it up.
export function safeChecksum(raw: string): string | null {
  try {
    return ethers.getAddress(raw);
  } catch {
    return null;
  }
}

export function winRatePct(fav: number, unfav: number): number {
  const total = fav + unfav;
  if (total === 0) return 0;
  return (fav / total) * 100;
}

// Format a signed USDC amount with leading +/- sign and absolute magnitude.
export function signedUsdc(amount: bigint): string {
  const sign = amount >= 0n ? "+" : "-";
  const magnitude = amount < 0n ? -amount : amount;
  return `${sign}$${formatUsdc(magnitude)}`;
}
