export enum SignalStatus {
  Active = 0,
  Cancelled = 1,
  Settled = 2,
}

export enum Outcome {
  Pending = 0,
  Favorable = 1,
  Unfavorable = 2,
  Void = 3,
}

export interface Signal {
  genius: string;
  encryptedBlob: string;
  commitHash: string;
  sport: string;
  maxPriceBps: bigint;
  slaMultiplierBps: bigint;
  maxNotional: bigint;
  minNotional: bigint;
  expiresAt: bigint;
  decoyLines: string[];
  availableSportsbooks: string[];
  status: SignalStatus;
  createdAt: bigint;
  linesHash: string;
  lineCount: number;
  bpaMode: boolean;
}

export interface Purchase {
  idiot: string;
  signalId: bigint;
  notional: bigint;
  feePaid: bigint;
  creditUsed: bigint;
  usdcPaid: bigint;
  odds: bigint;
  outcome: Outcome;
  purchasedAt: bigint;
  lockedOdds: bigint;
}

export interface AccountState {
  currentCycle: bigint;
  signalCount: bigint;
  qualityScore: bigint;
  purchaseIds: bigint[];
  settled: boolean;
}

/** v2 queue-based pair state */
export interface QueueState {
  totalPurchases: number;
  resolvedCount: number;
  auditedCount: number;
  auditBatchCount: number;
}

export interface GeniusLeaderboardEntry {
  address: string;
  qualityScore: number;
  totalSignals: number;
  auditCount: number;
  roi: number;
  proofCount: number;
  favCount: number;
  unfavCount: number;
  voidCount: number;
}

export interface CommitParams {
  signalId: bigint;
  encryptedBlob: string;
  commitHash: string;
  sport: string;
  maxPriceBps: bigint;
  slaMultiplierBps: bigint;
  maxNotional: bigint;
  minNotional: bigint;
  expiresAt: bigint;
  decoyLines: string[];
  availableSportsbooks: string[];
  linesHash: string;
  lineCount: number;
  bpaMode: boolean;
}

export function formatUsdc(amount: bigint): string {
  const whole = amount / 1_000_000n;
  const frac = amount % 1_000_000n;
  const fracStr = frac.toString().padStart(6, "0").replace(/0+$/, "");
  const wholeStr = Number(whole).toLocaleString("en-US");
  return fracStr ? `${wholeStr}.${fracStr}` : wholeStr;
}

// Quality Score is the net realized USDC (signed) from settled audits.
// We render it as currency with an explicit sign so positive vs. negative
// reads at a glance; uses U+2212 (unicode minus) instead of ASCII hyphen
// so the typography matches the "+" prefix in width.
export function formatQualityScore(score: number): string {
  const sign = score > 0 ? "+" : score < 0 ? "−" : "";
  const abs = Math.abs(score);
  return (
    sign +
    abs.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    })
  );
}

export const QUALITY_SCORE_TOOLTIP =
  "Quality Score is the net realized USDC across this genius's settled " +
  "audits. Positive means buyers profited on average; negative means " +
  "they lost. Unbounded; magnitude scales with total notional traded.";

export function parseUsdc(amount: string): bigint {
  const trimmed = amount.trim();
  if (!trimmed || !/^\d+(\.\d*)?$/.test(trimmed)) {
    throw new Error(`Invalid USDC amount: ${amount}`);
  }
  const [whole, frac = ""] = trimmed.split(".");
  const fracPadded = frac.padEnd(6, "0").slice(0, 6);
  const result = BigInt(whole) * 1_000_000n + BigInt(fracPadded);
  if (result < 0n) throw new Error("USDC amount must be non-negative");
  return result;
}

export function formatBps(bps: bigint): string {
  const pct = Number(bps) / 100;
  return `${pct}%`;
}

export function truncateAddress(address: string): string {
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

export function signalStatusLabel(status: SignalStatus): string {
  switch (status) {
    case SignalStatus.Active:
      return "Active";
    case SignalStatus.Cancelled:
      return "Cancelled";
    case SignalStatus.Settled:
      return "Settled";
  }
}

export function outcomeLabel(outcome: Outcome): string {
  switch (outcome) {
    case Outcome.Pending:
      return "Pending";
    case Outcome.Favorable:
      return "Favorable";
    case Outcome.Unfavorable:
      return "Unfavorable";
    case Outcome.Void:
      return "Void";
  }
}
