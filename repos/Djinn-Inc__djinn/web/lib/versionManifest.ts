/**
 * Maps validator-reported git_sha back to the real vNNNN tag.
 *
 * Some validator deployments pin a stale VERSION file (e.g. UID 213 reports
 * v999 forever) but still run recent code. The /health endpoint now also
 * returns git_sha; this manifest is generated at build time from every
 * vNNNN tag in the repo so the UI can surface the true running version.
 */
import { useQuery } from "@tanstack/react-query";

export interface VersionManifest {
  generated_at: string;
  count: number;
  shas: Record<string, string>;
}

export function resolveVersion(
  manifest: VersionManifest | undefined,
  gitSha: string | undefined | null,
): string | null {
  if (!manifest || !gitSha) return null;
  const shas = manifest.shas;
  const short = gitSha.slice(0, 7);
  return shas[short] ?? shas[gitSha] ?? null;
}

/** Strips leading "v" and everything after the first non-digit so "v1568+3" → 1568. */
function tagNumber(s: string | null | undefined): number | null {
  if (!s) return null;
  const m = String(s).match(/^v?(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

/** True when the reported version and the SHA-derived version disagree on the numeric tag. */
export function versionDrifts(
  reported: string | null | undefined,
  resolved: string | null | undefined,
): boolean {
  const r = tagNumber(reported);
  const e = tagNumber(resolved);
  return r != null && e != null && r !== e;
}

export function useVersionManifest() {
  return useQuery<VersionManifest>({
    queryKey: ["version-manifest"],
    queryFn: async () => {
      const r = await fetch("/versions.json", { cache: "force-cache" });
      if (!r.ok) throw new Error(`versions.json ${r.status}`);
      return (await r.json()) as VersionManifest;
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}
