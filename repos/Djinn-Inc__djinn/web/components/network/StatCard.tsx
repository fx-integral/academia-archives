interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  delta?: number | null;
  tone?: "default" | "warn" | "ok";
  /** When set, makes the card clickable and scrolls to `#${href}` on the page. */
  href?: string;
}

export default function StatCard({ label, value, sub, delta, tone = "default", href }: StatCardProps) {
  const valueClass =
    tone === "warn" ? "text-red-600" : tone === "ok" ? "text-emerald-600" : "";
  const subClass =
    tone === "warn" ? "text-red-500" : tone === "ok" ? "text-emerald-600" : "text-slate-400";
  const interactive = href ? "cursor-pointer hover:ring-2 hover:ring-slate-300 transition-shadow" : "";

  const handleClick = href
    ? () => {
        const el = document.getElementById(href);
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        // Async-loaded sections above the target (incentive chart,
        // scoring matrix, full miners table) can shift the page by
        // hundreds of pixels in the 1-2s after click, leaving the
        // user visually at the "wrong" place even though their scrollY
        // didn't change. Re-snap once after layout should be settled
        // — but only if the user hasn't deliberately scrolled away
        // in the meantime (compare scrollY against where the initial
        // smooth scroll landed).
        window.setTimeout(() => {
          const landedY = window.scrollY;
          window.setTimeout(() => {
            if (Math.abs(window.scrollY - landedY) > 5) return; // user moved, leave them alone
            const fresh = document.getElementById(href);
            fresh?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 1500);
        }, 600);
      }
    : undefined;

  return (
    <div
      className={`card text-center ${interactive}`}
      onClick={handleClick}
      role={href ? "button" : undefined}
      tabIndex={href ? 0 : undefined}
      onKeyDown={
        href
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                handleClick?.();
              }
            }
          : undefined
      }
    >
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs text-slate-400 uppercase tracking-wide">{label}</p>
        {delta != null && delta !== 0 && (
          <span
            className={`text-[11px] font-medium ${
              delta > 0 ? "text-emerald-600" : "text-red-500"
            }`}
          >
            {delta > 0 ? "\u25B2" : "\u25BC"} {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
      <p className={`text-2xl font-bold font-mono ${valueClass}`}>{value}</p>
      {sub && <p className={`text-[11px] ${subClass}`}>{sub}</p>}
    </div>
  );
}
