import { notFound } from "next/navigation";

import LineOutcomeChip from "@/components/LineOutcomeChip";
import { fetchLineByHash, isSubgraphConfigured } from "@/lib/subgraph";

/**
 * v1747 /verify/[lineHash] — public verifiability page.
 *
 * Shareable URL that resolves a single canonical line. Renders the
 * outcome, the attestor list (validator EOAs that signed), and a
 * Basescan tx link to the finalizing submit. The lineHash is content-
 * addressable across all signals that ever referenced the same line —
 * 100 signals containing "Lakers -3.5" all show the same proof here.
 */

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ lineHash: string }>;
}

function shortHash(addr: string): string {
  if (addr.length < 14) return addr;
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

export default async function VerifyLinePage({ params }: PageProps) {
  const { lineHash } = await params;

  // Strict validation: 0x + 64 hex chars (= 32 bytes lineHash).
  if (!/^0x[0-9a-fA-F]{64}$/.test(lineHash)) {
    notFound();
  }

  const subgraphReady = isSubgraphConfigured();
  const line = subgraphReady ? await fetchLineByHash(lineHash) : null;

  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      <header className="mb-8">
        <h1 className="text-3xl font-bold">Verify line</h1>
        <p className="mt-2 font-mono text-sm break-all text-slate-600">
          {lineHash}
        </p>
      </header>

      {!subgraphReady && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          The subgraph isn&apos;t configured yet. This page becomes live the
          moment the LineOutcomeRegistry is deployed and indexed.
        </div>
      )}

      {subgraphReady && !line && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-sm text-slate-700">
          <p className="font-medium">Not yet indexed.</p>
          <p className="mt-2 text-slate-600">
            This lineHash hasn&apos;t been observed on chain. Either the
            corresponding game hasn&apos;t resolved, no validator has yet
            attested, or the subgraph is still catching up.
          </p>
        </div>
      )}

      {line && (
        <section className="space-y-6">
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">
                  Canonical outcome
                </p>
                <div className="mt-2">
                  <LineOutcomeChip line={line} verbose linkToVerify={false} />
                </div>
              </div>
              {line.finalizedAtTx && (
                <a
                  href={`https://sepolia.basescan.org/tx/${line.finalizedAtTx}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline"
                >
                  Basescan tx →
                </a>
              )}
            </div>
            {line.finalizedAt && (
              <p className="mt-4 text-sm text-slate-600">
                Finalized at block {line.finalizedAtBlock} ·{" "}
                {new Date(Number(line.finalizedAt) * 1000).toUTCString()}
              </p>
            )}
            {line.forceVoided && line.voidReason && (
              <p className="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
                <span className="font-medium">Force-voided:</span> {line.voidReason}
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold">
              Attestations ({line.attestations.length})
            </h2>
            {line.attestations.length === 0 ? (
              <p className="mt-3 text-sm text-slate-600">
                No attestations submitted yet.
              </p>
            ) : (
              <ul className="mt-4 divide-y divide-slate-100">
                {line.attestations.map((att) => (
                  <li
                    key={att.id}
                    className="flex items-center justify-between py-3 text-sm"
                  >
                    <div>
                      <p className="font-mono">{shortHash(att.attestor)}</p>
                      <p className="text-xs text-slate-500">
                        Block {att.blockNumber}
                      </p>
                    </div>
                    <a
                      href={`https://sepolia.basescan.org/tx/${att.tx}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-600 hover:underline"
                    >
                      tx →
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
