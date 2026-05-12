"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAccount } from "wagmi";
import QualityScore from "@/components/QualityScore";
import { useAuditHistory } from "@/lib/hooks/useAuditHistory";
import { useLeaderboard } from "@/lib/hooks/useLeaderboard";
import { formatUsdc, formatQualityScore, truncateAddress } from "@/lib/types";
import { addressUrl } from "@/lib/explorer";
import { safeChecksum, signedUsdc, winRatePct } from "@/lib/geniusProfile";
import { profileIdentity } from "@/lib/profileIdentity";
import { useBlockTimestamps } from "@/lib/hooks/useBlockTimestamps";
import { formatBlockDate } from "@/lib/blockTime";

export default function GeniusProfileView() {
  const params = useParams();
  const raw = typeof params?.address === "string" ? params.address : "";
  const checksum = safeChecksum(raw);
  const { address: connected } = useAccount();
  const isSelf = Boolean(connected && checksum && connected.toLowerCase() === checksum.toLowerCase());

  const { audits, loading: auditsLoading, error: auditsError, aggregateQualityScore } = useAuditHistory(
    checksum ?? undefined,
  );
  const { data: leaderboard, loading: lbLoading } = useLeaderboard();
  const { timestamps: blockTimes } = useBlockTimestamps(
    useMemo(() => audits.map((a) => a.blockNumber), [audits]),
  );

  const lbEntry = useMemo(() => {
    if (!checksum) return undefined;
    const lower = checksum.toLowerCase();
    return leaderboard.find((e) => e.address.toLowerCase() === lower);
  }, [leaderboard, checksum]);

  const stats = useMemo(() => {
    if (!checksum) return null;
    const totalCycles = audits.length;
    const profitable = audits.filter((a) => a.qualityScore > 0n).length;
    const earlyExits = audits.filter((a) => a.isEarlyExit).length;
    const uniqueIdiots = new Set(audits.map((a) => a.idiot.toLowerCase())).size;
    return { totalCycles, profitable, earlyExits, uniqueIdiots };
  }, [audits, checksum]);

  if (!checksum) {
    return (
      <div className="max-w-3xl mx-auto py-12 text-center">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Invalid address</h1>
        <p className="text-slate-500 mb-6">
          The Genius address in the URL is malformed. Try the leaderboard.
        </p>
        <Link href="/leaderboard" className="text-genius-600 hover:text-genius-700 underline">
          Back to leaderboard
        </Link>
      </div>
    );
  }

  const fav = lbEntry?.favCount ?? 0;
  const unfav = lbEntry?.unfavCount ?? 0;
  const wr = winRatePct(fav, unfav);
  const totalSignals = lbEntry?.totalSignals ?? 0;
  const auditCount = lbEntry?.auditCount ?? audits.length;
  const roi = lbEntry?.roi ?? 0;
  const identity = profileIdentity(checksum);

  return (
    <div className="max-w-3xl mx-auto">
      <Link
        href="/leaderboard"
        className="text-sm text-slate-500 hover:text-slate-900 mb-6 inline-block transition-colors"
      >
        &larr; Back to leaderboard
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
        <div className="flex items-start gap-3">
          <div
            className="h-11 w-11 rounded-full text-sm font-semibold flex items-center justify-center shadow-sm shrink-0"
            style={identity.avatarStyle}
            aria-hidden="true"
            title={`@${identity.handle} avatar`}
          >
            {identity.initials}
          </div>
          <div>
            <h1 className="text-3xl font-bold text-slate-900 break-all">
              @{identity.handle}
            </h1>
            <p className="font-mono text-sm text-slate-500 mt-0.5">{truncateAddress(checksum)}</p>
            <p className="text-sm text-slate-500 mt-1">{identity.bio}</p>
          </div>
        </div>
        {lbEntry && lbEntry.auditCount > 0 ? (
          <QualityScore score={Math.round(lbEntry.qualityScore * 10) / 10} size="md" />
        ) : null}
      </div>

      <p className="text-slate-500 mb-2">
        Public Genius profile. All numbers below are computed from on-chain
        audit settlements and signal commitments.
      </p>

      <div className="flex flex-wrap items-center gap-3 mb-8 text-xs">
        <a
          href={addressUrl(checksum)}
          target="_blank"
          rel="noopener noreferrer"
          className="text-slate-500 hover:text-genius-600 underline"
        >
          View raw txs on Basescan
        </a>
        {isSelf && (
          <Link href="/genius" className="text-genius-600 hover:text-genius-700 underline">
            This is you. Open your dashboard.
          </Link>
        )}
      </div>

      {(auditsLoading || lbLoading) && (
        <div className="text-center py-8">
          <div className="inline-block w-6 h-6 border-2 border-genius-500 border-t-transparent rounded-full animate-spin mb-2" />
          <p className="text-xs text-slate-500">Loading on-chain history...</p>
        </div>
      )}

      {auditsError && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-3 mb-6" role="alert">
          <p className="text-xs text-red-600">{auditsError}</p>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="card text-center">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Lifetime Signals</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{totalSignals}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Audits</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{auditCount}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500 uppercase tracking-wide">ROI</p>
          {auditCount > 0 ? (
            <p className={`text-2xl font-bold mt-1 ${roi >= 0 ? "text-green-600" : "text-red-500"}`}>
              {roi >= 0 ? "+" : ""}
              {roi.toFixed(1)}%
            </p>
          ) : (
            <p className="text-2xl font-bold text-slate-400 mt-1">-</p>
          )}
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Win Rate</p>
          {fav + unfav > 0 ? (
            <p className="text-2xl font-bold text-slate-900 mt-1">
              {wr.toFixed(0)}%
              <span className="text-xs text-slate-400 ml-1 font-normal">
                ({fav}W/{unfav}L)
              </span>
            </p>
          ) : (
            <p className="text-2xl font-bold text-slate-400 mt-1">-</p>
          )}
        </div>
      </div>

      <div className="card mb-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-4">
          Settlement History
        </h2>
        {!auditsLoading && audits.length === 0 ? (
          <div className="text-center py-8 px-4">
            <p className="text-slate-700 font-medium mb-2">
              No settled audit batches yet.
            </p>
            <p className="text-sm text-slate-500 max-w-md mx-auto">
              This Genius has not yet had a buyer batch finalize on-chain. Once
              validators consensus-resolve a batch of their signals, the result
              will appear here and contribute to their Quality Score.
            </p>
          </div>
        ) : (
          <div className="space-y-3 max-h-[480px] overflow-y-auto">
            {audits.map((audit) => (
              <div
                key={`${audit.genius}-${audit.idiot}-${audit.cycle.toString()}`}
                className="flex items-center justify-between rounded-lg px-4 py-3 bg-slate-50 border border-slate-200"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-800">
                      Batch {audit.cycle.toString()}
                    </span>
                    <span
                      className="text-[10px] bg-slate-200 text-slate-500 rounded px-1.5 py-0.5"
                      title={audit.idiot}
                    >
                      Buyer {truncateAddress(audit.idiot)}
                    </span>
                    {audit.isEarlyExit && (
                      <span className="text-[10px] bg-amber-100 text-amber-600 rounded px-1.5 py-0.5">
                        Early Exit
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-500">
                    <span title={`Block ${audit.blockNumber}`}>{formatBlockDate(blockTimes.get(audit.blockNumber), audit.blockNumber)}</span>
                    <span>Tranche A: ${formatUsdc(audit.trancheA)}</span>
                    {audit.trancheB > 0n && (
                      <span>Tranche B: ${formatUsdc(audit.trancheB)}</span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <p className={`text-sm font-bold ${audit.qualityScore >= 0n ? "text-green-600" : "text-red-500"}`}>
                    {signedUsdc(audit.qualityScore)}
                  </p>
                </div>
              </div>
            ))}
            {audits.length > 0 && (
              <div className="flex items-center justify-between pt-3 border-t border-slate-200">
                <span className="text-sm font-medium text-slate-700">Aggregate Quality Score</span>
                <span className={`text-sm font-bold ${aggregateQualityScore >= 0 ? "text-green-600" : "text-red-500"}`}>
                  {formatQualityScore(aggregateQualityScore)}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {stats && stats.totalCycles > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-xs text-slate-500">
          <div className="card text-center">
            <p className="uppercase tracking-wide">Profitable Batches</p>
            <p className="text-base font-semibold text-slate-900 mt-1">
              {stats.profitable} / {stats.totalCycles}
            </p>
          </div>
          <div className="card text-center">
            <p className="uppercase tracking-wide">Early Exits</p>
            <p className="text-base font-semibold text-slate-900 mt-1">{stats.earlyExits}</p>
          </div>
          <div className="card text-center">
            <p className="uppercase tracking-wide">Unique Buyers</p>
            <p className="text-base font-semibold text-slate-900 mt-1">{stats.uniqueIdiots}</p>
          </div>
        </div>
      )}
    </div>
  );
}
