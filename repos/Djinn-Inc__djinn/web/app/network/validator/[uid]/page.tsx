import View from "./view";

/**
 * Sprint-B Stage-1: static-exportable shell. See /network/miner/[uid]/page.tsx
 * for rationale. SN103 UIDs are bounded 0..255; prerender every page.
 */
export function generateStaticParams() {
  return Array.from({ length: 256 }, (_, i) => ({ uid: String(i) }));
}

export default function Page() {
  return <View />;
}
