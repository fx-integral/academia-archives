"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function TrackRecordError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();

  useEffect(() => {
    console.error("Track record error:", error);
  }, [error]);

  return (
    <div className="max-w-2xl mx-auto text-center py-20">
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Track Record Error
      </h2>
      <p className="text-slate-600 mb-4">
        {error.message || "Failed to load the track record page."}
      </p>
      <p className="text-sm text-slate-400 mb-6">
        This may be caused by a proof generation failure or network issue.
      </p>
      <div className="flex gap-4 justify-center">
        <button
          onClick={reset}
          className="rounded-lg bg-slate-900 px-6 py-3 text-sm font-medium text-white hover:bg-slate-800 transition-colors"
        >
          Try again
        </button>
        <button
          onClick={() => router.push("/genius")}
          className="rounded-lg border border-slate-300 px-6 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors"
        >
          Back to Dashboard
        </button>
      </div>
    </div>
  );
}
