"use client";

import Link from "next/link";

import type { SubgraphLine } from "@/lib/subgraph";

/**
 * v1747: presentational chip for one canonical line outcome.
 *
 * Renders the canonical Outcome enum (Pending / Favorable / Unfavorable /
 * Void) with attestor count and an optional Basescan link to the
 * finalizing tx. Used on /genius/track-record per settled cycle and on
 * /idiot/signal/[id] post-game state, plus the standalone
 * /verify/[lineHash] page header.
 */

const COLOR: Record<SubgraphLine["outcome"], string> = {
  Pending: "bg-slate-100 text-slate-700 border-slate-200",
  Favorable: "bg-green-100 text-green-800 border-green-300",
  Unfavorable: "bg-red-100 text-red-800 border-red-300",
  Void: "bg-amber-100 text-amber-800 border-amber-300",
};

interface LineOutcomeChipProps {
  line: SubgraphLine;
  /** Optional plain-English label (e.g. "Lakers -3.5 spread"). */
  label?: string;
  /** Show the attestor count + Basescan tx link. Default false (compact mode). */
  verbose?: boolean;
  /** Link the chip to /verify/[lineHash] when true (default). */
  linkToVerify?: boolean;
}

export default function LineOutcomeChip({
  line,
  label,
  verbose = false,
  linkToVerify = true,
}: LineOutcomeChipProps) {
  const colorClass = COLOR[line.outcome];
  const attestorCount = line.attestations?.length ?? 0;
  const finalized = line.outcome !== "Pending";
  const txHref = line.finalizedAtTx
    ? `https://sepolia.basescan.org/tx/${line.finalizedAtTx}`
    : null;

  const chip = (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs font-medium ${colorClass}`}
      title={`Line ${line.id.slice(0, 10)}…${line.id.slice(-8)}`}
    >
      {label && <span className="font-sans">{label}</span>}
      <span>{line.outcome}</span>
      {verbose && finalized && (
        <span className="text-[10px] opacity-70">{attestorCount}/4 sigs</span>
      )}
      {line.forceVoided && (
        <span className="text-[10px] uppercase opacity-70">force-voided</span>
      )}
    </span>
  );

  if (linkToVerify) {
    return (
      <Link href={`/verify/${line.id}`} className="hover:opacity-80">
        {chip}
      </Link>
    );
  }
  if (verbose && txHref) {
    return (
      <a href={txHref} target="_blank" rel="noopener noreferrer" className="hover:opacity-80">
        {chip}
      </a>
    );
  }
  return chip;
}
