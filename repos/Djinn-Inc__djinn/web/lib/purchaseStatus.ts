import type { AuditEvent, SignalEvent } from "./events";

export type PurchaseStatusKind =
  | "active"
  | "expired"
  | "settled-favorable"
  | "settled-unfavorable"
  | "early-exit"
  | "pending";

export interface PurchaseStatus {
  kind: PurchaseStatusKind;
  label: string;
  tone: "sky" | "slate" | "green" | "red" | "amber";
  title: string;
}

const LABEL_BY_KIND: Record<PurchaseStatusKind, string> = {
  active: "Active",
  expired: "Expired",
  "settled-favorable": "Favorable",
  "settled-unfavorable": "Unfavorable",
  "early-exit": "Early Exit",
  pending: "Pending",
};

const TONE_BY_KIND: Record<PurchaseStatusKind, PurchaseStatus["tone"]> = {
  active: "sky",
  expired: "slate",
  "settled-favorable": "green",
  "settled-unfavorable": "red",
  "early-exit": "amber",
  pending: "slate",
};

const TITLE_BY_KIND: Record<PurchaseStatusKind, string> = {
  active: "Signal is still live; settlement happens after expiry.",
  expired: "Signal expired; awaiting batch audit settlement.",
  "settled-favorable": "Audit settled with a non-negative quality score.",
  "settled-unfavorable": "Audit settled with a negative quality score.",
  "early-exit": "Genius redeemed an early exit for this batch.",
  pending: "Status unknown; signal not currently in the active list and no audit found.",
};

const TONE_CLASSES: Record<PurchaseStatus["tone"], string> = {
  sky: "bg-sky-100 text-sky-700",
  slate: "bg-slate-100 text-slate-600",
  green: "bg-green-100 text-green-700",
  red: "bg-red-100 text-red-700",
  amber: "bg-amber-100 text-amber-700",
};

export function buildSignalLookup(signals: SignalEvent[]): Map<string, SignalEvent> {
  const m = new Map<string, SignalEvent>();
  for (const s of signals) m.set(s.signalId, s);
  return m;
}

function findCoveringAudit(
  signalGenius: string,
  purchaseBlock: number,
  audits: AuditEvent[],
): AuditEvent | undefined {
  const target = signalGenius.toLowerCase();
  let best: AuditEvent | undefined;
  for (const a of audits) {
    if (a.blockNumber <= purchaseBlock) continue;
    if (a.genius.toLowerCase() !== target) continue;
    if (!best || a.blockNumber < best.blockNumber) best = a;
  }
  return best;
}

function makeStatus(kind: PurchaseStatusKind): PurchaseStatus {
  return { kind, label: LABEL_BY_KIND[kind], tone: TONE_BY_KIND[kind], title: TITLE_BY_KIND[kind] };
}

export function resolvePurchaseStatus(
  purchase: { signalId: string; blockNumber: number },
  signal: SignalEvent | undefined,
  audits: AuditEvent[],
  nowSec: bigint,
): PurchaseStatus {
  if (signal) {
    const covering = findCoveringAudit(signal.genius, purchase.blockNumber, audits);
    if (covering) {
      if (covering.isEarlyExit) return makeStatus("early-exit");
      return makeStatus(covering.qualityScore >= 0n ? "settled-favorable" : "settled-unfavorable");
    }
    return makeStatus(signal.expiresAt > nowSec ? "active" : "expired");
  }
  return makeStatus("pending");
}

export function purchaseStatusClasses(status: PurchaseStatus): string {
  return TONE_CLASSES[status.tone];
}
