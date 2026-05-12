/**
 * Maps guessable returning-user URLs (e.g. /idiot/history, /settings) to the
 * canonical dashboard section that fulfills that intent. Each entry is a
 * { source, destination } pair; the destination may include a `#section-id`
 * hash so the dashboard scrolls to the matching `<section id="...">`.
 *
 * The list is consumed by `next.config.js#redirects()` and exercised by
 * `__tests__/dashboardRedirects.test.ts`. Keep destinations in sync with the
 * `id="..."` attributes on `<section>` elements in
 * `web/app/idiot/page.tsx` and `web/app/genius/page.tsx`.
 *
 * `permanent: false` (307) is intentional: each alias may be promoted to a
 * real route later, and 307 leaves the door open without poisoning browser
 * caches.
 */

export interface DashboardRedirect {
  source: string;
  destination: string;
  permanent: false;
}

export const DASHBOARD_REDIRECTS: ReadonlyArray<DashboardRedirect> = [
  { source: "/idiot/history", destination: "/idiot#purchase-history", permanent: false },
  { source: "/idiot/portfolio", destination: "/idiot#purchase-history", permanent: false },
  { source: "/idiot/purchases", destination: "/idiot#purchase-history", permanent: false },
  { source: "/idiot/dashboard", destination: "/idiot", permanent: false },
  { source: "/genius/history", destination: "/genius#history", permanent: false },
  { source: "/genius/dashboard", destination: "/genius", permanent: false },
  { source: "/genius/signals", destination: "/genius#signals", permanent: false },
  { source: "/dashboard", destination: "/idiot", permanent: false },
  { source: "/profile", destination: "/idiot", permanent: false },
  { source: "/settings", destination: "/idiot#balance", permanent: false },
];

export const DASHBOARD_SECTION_IDS = {
  idiot: ["balance", "browse", "purchase-history", "relationships", "settlements"],
  genius: ["collateral", "signals", "relationships", "history"],
} as const;

export function findDashboardRedirect(
  pathname: string,
): DashboardRedirect | undefined {
  return DASHBOARD_REDIRECTS.find((r) => r.source === pathname);
}
