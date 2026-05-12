export default function CreateSignalLoading() {
  return (
    <div className="max-w-2xl mx-auto py-10">
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-slate-200 rounded w-48" />
        <div className="h-4 bg-slate-200 rounded w-96" />
        <div className="space-y-3">
          {Array.from({ length: 10 }, (_, i) => (
            <div key={i} className="h-10 bg-slate-200 rounded" />
          ))}
        </div>
        <div className="h-12 bg-slate-200 rounded" />
      </div>
    </div>
  );
}
