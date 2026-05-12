"use client";

import { useEffect } from "react";

export default function LeaderboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Leaderboard error:", error);
  }, [error]);

  return (
    <div className="max-w-2xl mx-auto text-center py-20">
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Leaderboard Error
      </h2>
      <p className="text-slate-600 mb-4">
        {error.message || "Failed to load the leaderboard."}
      </p>
      <p className="text-sm text-slate-400 mb-6">
        This may be caused by a network issue or subgraph indexing delay.
      </p>
      <button
        onClick={reset}
        className="rounded-lg bg-slate-900 px-6 py-3 text-sm font-medium text-white hover:bg-slate-800 transition-colors"
      >
        Try again
      </button>
    </div>
  );
}
