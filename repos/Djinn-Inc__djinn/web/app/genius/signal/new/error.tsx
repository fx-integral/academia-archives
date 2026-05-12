"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function NewSignalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();

  useEffect(() => {
    console.error("New signal error:", error);
  }, [error]);

  return (
    <div className="max-w-2xl mx-auto text-center py-20">
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Signal Creation Error
      </h2>
      <p className="text-slate-600 mb-4">
        {error.message || "Failed to load the signal creation page."}
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
