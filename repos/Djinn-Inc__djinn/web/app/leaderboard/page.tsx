"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import QualityScore from "@/components/QualityScore";
import { useLeaderboard } from "@/lib/hooks/useLeaderboard";
import { truncateAddress } from "@/lib/types";
import { addressUrl } from "@/lib/explorer";
import { leaderboardStatus } from "@/lib/leaderboardStatus";
import { profileIdentity } from "@/lib/profileIdentity";
import {
  MIN_AUDITS_FILTER_OPTIONS,
  WIN_RATE_MIN_AUDITS_DEFAULT,
  classifySample,
  meetsMinAudits,
  winRateLowerBound,
  winRatePercent,
  winRateSampleSize,
  type MinAuditsFilter,
} from "@/lib/winRateConfidence";

type SortField = "qualityScore" | "totalSignals" | "auditCount" | "roi" | "proofCount" | "winRate";

export default function Leaderboard() {
  const { data, loading, error, configured } = useLeaderboard();
  const status = leaderboardStatus(data);
  const [userSortBy, setUserSortBy] = useState<SortField | null>(null);
  const [sortDesc, setSortDesc] = useState(true);
  const [copiedAddr, setCopiedAddr] = useState<string | null>(null);
  const [minAudits, setMinAudits] = useState<MinAuditsFilter>(WIN_RATE_MIN_AUDITS_DEFAULT);
  const sortBy: SortField =
    userSortBy ?? (status.phase === "preAudit" ? "totalSignals" : "qualityScore");
  const winRateFilterActive = sortBy === "winRate" && minAudits > 0;

  const copyAddress = useCallback((addr: string) => {
    navigator.clipboard.writeText(addr);
    setCopiedAddr(addr);
    setTimeout(() => setCopiedAddr(null), 1500);
  }, []);

  const filtered = useMemo(
    () =>
      winRateFilterActive
        ? data.filter((entry) => meetsMinAudits(entry, minAudits))
        : data,
    [data, winRateFilterActive, minAudits],
  );
  const hiddenByFilter = winRateFilterActive ? data.length - filtered.length : 0;

  const sorted = [...filtered].sort((a, b) => {
    const multiplier = sortDesc ? -1 : 1;
    if (sortBy === "winRate") {
      return (winRateLowerBound(a) - winRateLowerBound(b)) * multiplier;
    }
    return (a[sortBy] - b[sortBy]) * multiplier;
  });

  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortDesc((v) => !v);
    } else {
      setUserSortBy(field);
      setSortDesc(true);
    }
  };

  const sortIndicator = (field: SortField) => {
    if (sortBy !== field) return "";
    return sortDesc ? " \u2193" : " \u2191";
  };

  const ariaSort = (field: SortField): "ascending" | "descending" | "none" => {
    if (sortBy !== field) return "none";
    return sortDesc ? "descending" : "ascending";
  };

  const sortKeyHandler = (field: SortField) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleSort(field);
    }
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900">Genius Leaderboard</h1>
        <p className="text-slate-500 mt-1">
          Geniuses ranked by cryptographically verified track records
        </p>
      </div>

      {!configured && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 mb-6 text-sm text-amber-700">
          The leaderboard is being set up. Check back soon to see Genius rankings.
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 mb-6 text-sm text-red-600">
          {error}
        </div>
      )}

      {!loading && status.hasAnyEntries && status.phase === "preAudit" && (
        <div
          className="rounded-lg bg-sky-50 border border-sky-200 px-4 py-3 mb-6 text-sm text-sky-800"
          data-testid="leaderboard-preaudit-banner"
        >
          <p className="font-medium text-sky-900">Pre-audit phase</p>
          <p className="mt-1 text-sky-800">
            No audit batch has settled yet on Base Sepolia, so Quality Score, ROI, and Win Rate are
            still pending. Geniuses below are temporarily ordered by signal count. Rankings activate
            once the first batch resolves; check back after the next validator audit.
          </p>
        </div>
      )}

      {!loading && status.phase === "active" && (
        <div
          className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3 text-xs text-slate-600"
          data-testid="leaderboard-winrate-controls"
        >
          <label className="inline-flex items-center gap-2">
            <span className="font-medium text-slate-700">Win Rate filter:</span>
            <select
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-genius-500/40"
              value={minAudits}
              onChange={(e) => setMinAudits(Number(e.target.value) as MinAuditsFilter)}
              aria-label="Minimum settled audits required to appear when sorting by Win Rate"
            >
              {MIN_AUDITS_FILTER_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? "Show all samples" : `Min ${n} settled audits`}
                </option>
              ))}
            </select>
          </label>
          <p className="text-slate-500">
            Win Rate sort uses a 95% Wilson lower bound so a 2/0 (100%) genius cannot outrank a
            130/70 (65%) one. Rows below {`${minAudits}`} settled audits hide while sorting by Win Rate.
          </p>
        </div>
      )}

      {winRateFilterActive && hiddenByFilter > 0 && (
        <p
          className="mb-3 text-xs text-slate-500"
          data-testid="leaderboard-winrate-hidden-count"
        >
          {hiddenByFilter} {hiddenByFilter === 1 ? "Genius" : "Geniuses"} hidden by the
          ≥{minAudits}-audit filter. Lower the threshold to include them.
        </p>
      )}

      {/* Mobile sort control (visible <lg only). Desktop uses clickable column headers. */}
      {!loading && sorted.length > 0 && (
        <div className="lg:hidden mb-3 flex items-center gap-2 text-xs text-slate-600">
          <label className="inline-flex items-center gap-2 w-full">
            <span className="font-medium text-slate-700 shrink-0">Sort by:</span>
            <select
              className="flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-genius-500/40"
              value={`${sortBy}:${sortDesc ? "desc" : "asc"}`}
              onChange={(e) => {
                const [field, dir] = e.target.value.split(":") as [SortField, "desc" | "asc"];
                setUserSortBy(field);
                setSortDesc(dir === "desc");
              }}
              aria-label="Sort leaderboard"
              data-testid="leaderboard-mobile-sort"
            >
              <option value="qualityScore:desc">Quality Score (high to low)</option>
              <option value="totalSignals:desc">Signals (high to low)</option>
              <option value="auditCount:desc">Audits (high to low)</option>
              <option value="roi:desc">ROI (high to low)</option>
              <option value="proofCount:desc">Proofs (high to low)</option>
              <option value="winRate:desc">Win Rate (high to low)</option>
            </select>
          </label>
        </div>
      )}

      <div className="card overflow-x-auto hidden lg:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="pb-3 font-medium w-12 whitespace-nowrap">#</th>
              <th className="pb-3 font-medium whitespace-nowrap">Genius</th>
              <th
                className="pb-3 font-medium cursor-pointer hover:text-slate-900 transition-colors whitespace-nowrap"
                onClick={() => handleSort("qualityScore")}
                onKeyDown={sortKeyHandler("qualityScore")}
                aria-sort={ariaSort("qualityScore")}
                tabIndex={0}
                role="columnheader"
              >
                Quality Score{sortIndicator("qualityScore")}
              </th>
              <th
                className="pb-3 font-medium cursor-pointer hover:text-slate-900 transition-colors whitespace-nowrap"
                onClick={() => handleSort("totalSignals")}
                onKeyDown={sortKeyHandler("totalSignals")}
                aria-sort={ariaSort("totalSignals")}
                tabIndex={0}
                role="columnheader"
              >
                Signals{sortIndicator("totalSignals")}
              </th>
              <th
                className="pb-3 font-medium cursor-pointer hover:text-slate-900 transition-colors whitespace-nowrap"
                onClick={() => handleSort("auditCount")}
                onKeyDown={sortKeyHandler("auditCount")}
                aria-sort={ariaSort("auditCount")}
                tabIndex={0}
                role="columnheader"
              >
                Audits{sortIndicator("auditCount")}
              </th>
              <th
                className="pb-3 font-medium cursor-pointer hover:text-slate-900 transition-colors whitespace-nowrap"
                onClick={() => handleSort("roi")}
                onKeyDown={sortKeyHandler("roi")}
                aria-sort={ariaSort("roi")}
                tabIndex={0}
                role="columnheader"
              >
                ROI{sortIndicator("roi")}
              </th>
              <th
                className="pb-3 font-medium cursor-pointer hover:text-slate-900 transition-colors whitespace-nowrap"
                onClick={() => handleSort("proofCount")}
                onKeyDown={sortKeyHandler("proofCount")}
                aria-sort={ariaSort("proofCount")}
                tabIndex={0}
                role="columnheader"
              >
                Proofs{sortIndicator("proofCount")}
              </th>
              <th
                className="pb-3 font-medium cursor-pointer hover:text-slate-900 transition-colors whitespace-nowrap"
                onClick={() => handleSort("winRate")}
                onKeyDown={sortKeyHandler("winRate")}
                aria-sort={ariaSort("winRate")}
                tabIndex={0}
                role="columnheader"
              >
                Win Rate{sortIndicator("winRate")}
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <>
                {[1, 2, 3, 4, 5].map((i) => (
                  <tr key={i} className="border-b border-slate-200 animate-pulse">
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-6" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-200 rounded w-24" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-16" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-10" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-10" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-14" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-8" /></td>
                    <td className="py-4"><div className="h-4 bg-slate-100 rounded w-20" /></td>
                  </tr>
                ))}
              </>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center text-slate-500 py-12">
                  {winRateFilterActive && data.length > 0
                    ? `No Geniuses meet the ≥${minAudits}-audit filter yet. Lower the threshold to see smaller samples.`
                    : "No Geniuses with signal activity yet. Rankings will appear once signals are created on-chain."}
                </td>
              </tr>
            ) : (
              sorted.map((entry, i) => {
                const id = profileIdentity(entry.address);
                return (
                <tr key={entry.address} className="border-b border-slate-200 hover:bg-slate-50 transition-colors">
                  <td className="py-4 text-slate-500 font-mono align-top">{i + 1}</td>
                  <td className="py-4 align-top">
                    <div className="flex items-start gap-3">
                      <div
                        className="h-8 w-8 rounded-full text-[11px] font-semibold flex items-center justify-center shadow-sm shrink-0"
                        style={id.avatarStyle}
                        aria-hidden="true"
                        title={`@${id.handle} avatar`}
                      >
                        {id.initials}
                      </div>
                      <div className="min-w-0">
                        <div className="inline-flex items-center gap-2 flex-wrap">
                          <Link
                            href={`/genius/${entry.address}`}
                            className="text-slate-900 hover:text-genius-600 transition-colors font-semibold underline-offset-2 hover:underline"
                            title="View Genius profile"
                          >
                            @{id.handle}
                          </Link>
                          <span className="font-mono text-xs text-slate-500">{truncateAddress(entry.address)}</span>
                        </div>
                        <p className="hidden sm:block text-xs text-slate-500 mt-0.5 line-clamp-2">{id.bio}</p>
                        <div className="inline-flex items-center gap-2 mt-1">
                          <button
                            type="button"
                            className="text-slate-300 hover:text-genius-600 transition-colors"
                            title="Copy full address"
                            aria-label="Copy address"
                            onClick={() => copyAddress(entry.address)}
                          >
                            {copiedAddr === entry.address ? (
                              <span className="text-[10px] font-sans text-green-600 font-medium">Copied!</span>
                            ) : (
                              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                              </svg>
                            )}
                          </button>
                          <a
                            href={addressUrl(entry.address)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-slate-400 hover:text-genius-600 transition-colors"
                            title="View raw txs on Basescan"
                            aria-label="View raw txs on Basescan"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                            </svg>
                          </a>
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="py-4">
                    {entry.auditCount > 0 ? (
                      <QualityScore score={entry.qualityScore} size="sm" />
                    ) : (
                      <span className="text-slate-400" title="No resolved audits yet">-</span>
                    )}
                  </td>
                  <td className="py-4 text-slate-900">{entry.totalSignals}</td>
                  <td className="py-4 text-slate-900">{entry.auditCount}</td>
                  <td className="py-4">
                    {entry.auditCount > 0 ? (
                      <span
                        className={
                          entry.roi >= 0 ? "text-green-600" : "text-red-600"
                        }
                      >
                        {entry.roi >= 0 ? "+" : ""}
                        {entry.roi.toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-slate-400" title="No resolved audits yet">-</span>
                    )}
                  </td>
                  <td className="py-4 text-slate-900">{entry.proofCount}</td>
                  <td className="py-4">
                    {(() => {
                      const sampleClass = classifySample(entry);
                      if (sampleClass === "none") {
                        return <span className="text-slate-400">-</span>;
                      }
                      const lowSample = sampleClass === "small" || sampleClass === "modest";
                      return (
                        <span
                          className={
                            lowSample
                              ? "text-slate-500 inline-flex items-center gap-1.5"
                              : "text-slate-900 inline-flex items-center gap-1.5"
                          }
                        >
                          <span>{winRatePercent(entry).toFixed(0)}%</span>
                          <span className="text-xs text-slate-400">
                            ({entry.favCount}W/{entry.unfavCount}L{entry.voidCount > 0 ? `/${entry.voidCount}V` : ""})
                          </span>
                          {lowSample && (
                            <span
                              className="text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200"
                              title={`Small sample: only ${winRateSampleSize(entry)} settled audit${winRateSampleSize(entry) === 1 ? "" : "s"}. Rate is noisy until ≥${WIN_RATE_MIN_AUDITS_DEFAULT}.`}
                              data-testid="winrate-low-sample-badge"
                            >
                              small sample
                            </span>
                          )}
                        </span>
                      );
                    })()}
                  </td>
                </tr>
              );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile card list (visible <lg only). Mirrors the table data with all metrics
          stacked in a 2-col grid so ROI/Proofs/Win Rate are visible without horizontal scroll. */}
      <div className="lg:hidden space-y-3" data-testid="leaderboard-mobile-list">
        {loading ? (
          [1, 2, 3].map((i) => (
            <div key={i} className="card animate-pulse">
              <div className="h-5 w-32 rounded bg-slate-200" />
              <div className="mt-3 grid grid-cols-2 gap-2">
                {[1, 2, 3, 4, 5, 6].map((j) => (
                  <div key={j} className="h-4 rounded bg-slate-100" />
                ))}
              </div>
            </div>
          ))
        ) : sorted.length === 0 ? (
          <div className="card text-center text-sm text-slate-500 py-8">
            {winRateFilterActive && data.length > 0
              ? `No Geniuses meet the ≥${minAudits}-audit filter yet. Lower the threshold to see smaller samples.`
              : "No Geniuses with signal activity yet. Rankings will appear once signals are created on-chain."}
          </div>
        ) : (
          sorted.map((entry, i) => {
            const id = profileIdentity(entry.address);
            const sampleClass = classifySample(entry);
            const lowSample = sampleClass === "small" || sampleClass === "modest";
            return (
              <Link
                key={entry.address}
                href={`/genius/${entry.address}`}
                className="card block hover:border-genius-200 transition-colors"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <span className="text-slate-400 font-mono text-sm shrink-0 mt-1">{i + 1}</span>
                    <div
                      className="h-9 w-9 rounded-full text-[12px] font-semibold flex items-center justify-center shadow-sm shrink-0"
                      style={id.avatarStyle}
                      aria-hidden="true"
                    >
                      {id.initials}
                    </div>
                    <div className="min-w-0">
                      <p className="text-slate-900 font-semibold truncate">@{id.handle}</p>
                      <p className="font-mono text-xs text-slate-500 truncate">{truncateAddress(entry.address)}</p>
                    </div>
                  </div>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                  <div className="flex items-baseline justify-between border-b border-slate-100 pb-1">
                    <dt className="text-slate-500">Quality Score</dt>
                    <dd className="text-slate-900 font-medium">
                      {entry.auditCount > 0 ? entry.qualityScore.toFixed(0) : "—"}
                    </dd>
                  </div>
                  <div className="flex items-baseline justify-between border-b border-slate-100 pb-1">
                    <dt className="text-slate-500">Signals</dt>
                    <dd className="text-slate-900 font-medium">{entry.totalSignals}</dd>
                  </div>
                  <div className="flex items-baseline justify-between border-b border-slate-100 pb-1">
                    <dt className="text-slate-500">Audits</dt>
                    <dd className="text-slate-900 font-medium">{entry.auditCount}</dd>
                  </div>
                  <div className="flex items-baseline justify-between border-b border-slate-100 pb-1">
                    <dt className="text-slate-500">ROI</dt>
                    <dd className={entry.auditCount > 0 ? (entry.roi >= 0 ? "text-green-600 font-medium" : "text-red-600 font-medium") : "text-slate-400"}>
                      {entry.auditCount > 0
                        ? `${entry.roi >= 0 ? "+" : ""}${entry.roi.toFixed(1)}%`
                        : "—"}
                    </dd>
                  </div>
                  <div className="flex items-baseline justify-between border-b border-slate-100 pb-1">
                    <dt className="text-slate-500">Proofs</dt>
                    <dd className="text-slate-900 font-medium">{entry.proofCount}</dd>
                  </div>
                  <div className="flex items-baseline justify-between border-b border-slate-100 pb-1">
                    <dt className="text-slate-500">Win Rate</dt>
                    <dd className={lowSample ? "text-slate-500" : "text-slate-900 font-medium"}>
                      {sampleClass === "none"
                        ? "—"
                        : `${winRatePercent(entry).toFixed(0)}% (${entry.favCount}/${entry.unfavCount + entry.favCount})`}
                    </dd>
                  </div>
                </dl>
                {lowSample && (
                  <p className="mt-2 text-[10px] uppercase tracking-wide font-medium text-amber-700">
                    Small sample ({winRateSampleSize(entry)} settled audit{winRateSampleSize(entry) === 1 ? "" : "s"})
                  </p>
                )}
              </Link>
            );
          })
        )}
      </div>

      {/* Explanation */}
      <div className="mt-8 card">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          How Quality Score Works
        </h2>
        <div className="text-sm text-slate-500 space-y-2">
          <p>
            Quality Score (QS) is the on-chain measure of a Genius&apos;s prediction
            accuracy, computed across each audit batch:
          </p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>
              <span className="text-green-600">Favorable:</span> +Notional &times; (odds &minus; 1)
            </li>
            <li>
              <span className="text-red-600">Unfavorable:</span> &minus;Notional &times; Backing%
            </li>
            <li>
              <span className="text-slate-500">Void:</span> does not count
            </li>
          </ul>
          <p>
            Once enough signals between a Genius-Idiot pair have resolved, a validator
            audit verifies the Quality Score on-chain. If the score is negative, the
            Genius&apos;s collateral is slashed: the Idiot receives a USDC refund
            (up to fees paid) plus Djinn Credits for excess damages.
          </p>
        </div>
      </div>
    </div>
  );
}
