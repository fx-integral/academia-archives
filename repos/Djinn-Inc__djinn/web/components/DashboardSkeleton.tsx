/** Skeleton loading states for dashboards. */

export default function DashboardSkeleton() {
  return (
    <div className="animate-pulse space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="h-8 bg-slate-200 rounded-lg w-56" />
          <div className="h-4 bg-slate-100 rounded w-72 mt-2" />
        </div>
        <div className="flex gap-3">
          <div className="h-9 bg-slate-200 rounded-lg w-28" />
          <div className="h-9 bg-slate-200 rounded-lg w-28" />
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <StatCardSkeleton key={i} />
        ))}
      </div>

      {/* Section */}
      <div>
        <div className="h-6 bg-slate-200 rounded w-36 mb-4" />
        <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
          {[1, 2, 3].map((i) => (
            <TableRowSkeleton key={i} />
          ))}
        </div>
      </div>

      {/* Another section */}
      <div>
        <div className="h-6 bg-slate-200 rounded w-44 mb-4" />
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <div className="h-4 bg-slate-100 rounded w-full mb-3" />
          <div className="h-4 bg-slate-100 rounded w-3/4 mb-3" />
          <div className="h-4 bg-slate-100 rounded w-1/2" />
        </div>
      </div>
    </div>
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="h-3 bg-slate-100 rounded w-20 mb-3" />
      <div className="h-7 bg-slate-200 rounded w-24 mb-2" />
      <div className="h-3 bg-slate-100 rounded w-28" />
    </div>
  );
}

export function TableRowSkeleton() {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex-1">
        <div className="h-4 bg-slate-200 rounded w-48 mb-1.5" />
        <div className="h-3 bg-slate-100 rounded w-64" />
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-4">
        <div className="h-6 bg-slate-100 rounded-full w-16" />
        <div className="h-4 bg-slate-100 rounded w-4" />
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="animate-pulse rounded-xl border border-slate-200 bg-white p-4 space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <TableRowSkeleton key={i} />
      ))}
    </div>
  );
}
