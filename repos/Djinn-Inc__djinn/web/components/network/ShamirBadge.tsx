export interface ShamirBadgeProps {
  threshold?: number | null;
}

// Client-side target. SHAMIR_MIN=SHAMIR_MAX=2 in the bootstrap window;
// validators stranded at 7 after v1556 silently skip reconstruction.
const CLIENT_TARGET = 2;

export default function ShamirBadge({ threshold }: ShamirBadgeProps) {
  if (threshold === null || threshold === undefined) {
    return <span className="text-slate-300">-</span>;
  }
  const stranded = threshold !== CLIENT_TARGET;
  const cls = stranded
    ? "bg-amber-100 text-amber-700"
    : "bg-emerald-100 text-emerald-700";
  const label = stranded ? `st=${threshold} !` : `st=${threshold}`;
  const title = stranded
    ? `Shamir threshold ${threshold} != client target ${CLIENT_TARGET}. Pull v1556+ and restart.`
    : `Shamir threshold matches client (st=${CLIENT_TARGET})`;
  return (
    <span
      className={`text-[11px] font-medium px-2 py-0.5 rounded-full font-mono ${cls}`}
      title={title}
    >
      {label}
    </span>
  );
}
