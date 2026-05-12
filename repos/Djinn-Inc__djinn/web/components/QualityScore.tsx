"use client";

import { formatQualityScore, QUALITY_SCORE_TOOLTIP } from "@/lib/types";

interface QualityScoreProps {
  /** Net realized USDC gain/loss across settled audits (dollars, signed). */
  score: number;
  size?: "sm" | "md" | "lg";
}

// Tier thresholds in USDC. A "strong" outcome is one whose realized P&L is
// meaningfully large compared to typical signal notional ($1–$1000 range).
// The buckets exist to give the UI a stable visual signal at a glance —
// they are not used by any economic computation.
const STRONG_POSITIVE = 100; // ≥ +$100 realized
const STRONG_NEGATIVE = -100; // ≤ -$100 realized

function scoreColor(score: number): string {
  if (score >= STRONG_POSITIVE) return "text-green-600";
  if (score > 0) return "text-green-500";
  if (score === 0) return "text-slate-500";
  if (score > STRONG_NEGATIVE) return "text-genius-500";
  return "text-red-600";
}

function scoreBg(score: number): string {
  if (score >= STRONG_POSITIVE) return "bg-green-100 border-green-200";
  if (score > 0) return "bg-green-50 border-green-100";
  if (score === 0) return "bg-slate-100 border-slate-200";
  if (score > STRONG_NEGATIVE) return "bg-orange-50 border-orange-100";
  return "bg-red-100 border-red-200";
}

function sizeClasses(size: "sm" | "md" | "lg"): string {
  switch (size) {
    case "sm":
      return "text-lg px-3 py-1";
    case "md":
      return "text-2xl px-4 py-2";
    case "lg":
      return "text-4xl px-6 py-3";
  }
}

export default function QualityScore({ score, size = "md" }: QualityScoreProps) {
  return (
    <div
      title={QUALITY_SCORE_TOOLTIP}
      className={`inline-flex items-center rounded-xl border font-mono font-bold ${scoreColor(score)} ${scoreBg(score)} ${sizeClasses(size)}`}
    >
      <span className="mr-1 text-xs font-normal uppercase tracking-wide opacity-60">
        QS
      </span>
      {formatQualityScore(score)}
    </div>
  );
}
