// Base chain explorer URL helper. Defaults to Sepolia for testnet; mainnet
// deploy flips NEXT_PUBLIC_BASE_EXPLORER via build env. Single source so we
// don't end up with the current pattern where /admin defaults to mainnet but
// /admin/mission-control defaults to Sepolia.

const DEFAULT_EXPLORER = "https://sepolia.basescan.org";

export function baseExplorerUrl(): string {
  if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_BASE_EXPLORER) {
    return process.env.NEXT_PUBLIC_BASE_EXPLORER;
  }
  return DEFAULT_EXPLORER;
}

export function addressUrl(address: string): string {
  return `${baseExplorerUrl()}/address/${address}`;
}

export function txUrl(txHash: string): string {
  return `${baseExplorerUrl()}/tx/${txHash}`;
}
