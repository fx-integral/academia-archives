"use client";

import { useEffect, useRef, useState } from "react";
import ReportErrorModal from "@/components/ReportError";
import { fetchFromAnyValidator } from "@/lib/api";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [reportOpen, setReportOpen] = useState(false);
  // Dedup by digest so clicking "Try again" and hitting a DIFFERENT error
  // still reports the new one. Old boolean guard silently dropped every
  // crash after the first within the same mount. Fallback to message when
  // Next.js hasn't produced a digest (dev builds).
  const reportedDedupKeyRef = useRef<string | null>(null);

  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  useEffect(() => {
    const dedupKey = error.digest ?? error.message;
    if (reportedDedupKeyRef.current === dedupKey) return;
    reportedDedupKeyRef.current = dedupKey;
    fetchFromAnyValidator("/v1/report-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `Crash: ${error.message}`,
        url: typeof window !== "undefined" ? window.location.pathname : "",
        errorMessage: error.message,
        errorStack: error.stack?.slice(0, 2000),
        userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "",
        source: "error-boundary",
      }),
    }).catch(() => {});
  }, [error]);

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center px-4">
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Something went wrong
      </h2>
      <p className="text-slate-600 mb-6 text-center max-w-md">
        {error.message || "An unexpected error occurred."}
      </p>
      <div className="flex gap-3">
        <button
          onClick={reset}
          className="rounded-lg bg-slate-900 px-6 py-3 text-sm font-medium text-white hover:bg-slate-800 transition-colors"
        >
          Try again
        </button>
        <button
          onClick={() => setReportOpen(true)}
          className="rounded-lg border border-slate-300 px-6 py-3 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors"
        >
          Report this error
        </button>
      </div>
      <p className="text-xs text-slate-400 mt-4">This error has been automatically reported.</p>

      <ReportErrorModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        error={error}
        source="error-boundary"
      />
    </div>
  );
}
