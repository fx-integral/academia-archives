export default function SignalDetailLoading() {
  return (
    <div className="max-w-2xl mx-auto py-10">
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-slate-200 rounded w-48" />
        <div className="h-32 bg-slate-200 rounded-lg" />
        <div className="h-4 bg-slate-200 rounded w-64" />
        <div className="grid grid-cols-2 gap-4">
          <div className="h-24 bg-slate-200 rounded-lg" />
          <div className="h-24 bg-slate-200 rounded-lg" />
        </div>
        <div className="h-12 bg-slate-200 rounded" />
      </div>
    </div>
  );
}
