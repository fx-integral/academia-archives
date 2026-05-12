import { NextResponse } from "next/server";
import { fetchLeaderboard, isSubgraphConfigured } from "@/lib/subgraph";

export const revalidate = 30;

export async function GET(request: Request) {
  if (!isSubgraphConfigured()) {
    return NextResponse.json(
      { geniuses: [], reason: "subgraph_not_configured" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const url = new URL(request.url);
  const limitParam = url.searchParams.get("limit");
  const parsed = limitParam ? Number.parseInt(limitParam, 10) : 100;
  const limit = Number.isFinite(parsed) ? Math.max(1, Math.min(1000, parsed)) : 100;

  try {
    const geniuses = await fetchLeaderboard(limit);
    return NextResponse.json(
      { geniuses },
      {
        headers: {
          "Cache-Control": "public, s-maxage=30, stale-while-revalidate=120",
        },
      },
    );
  } catch (err) {
    return NextResponse.json(
      { geniuses: [], error: err instanceof Error ? err.message : "unknown" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
