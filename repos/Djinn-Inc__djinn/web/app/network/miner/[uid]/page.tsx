import View from "./view";

/**
 * Sprint-B Stage-1: static-exportable shell.
 *
 * SN103 UIDs are bounded 0..255, so we can prerender every page at build
 * time and ship them from any static host (Cloudflare Pages / IPFS). The
 * actual component is in `view.tsx` which reads `uid` via `useParams()`;
 * this file is purely the server boundary that exists only so
 * `generateStaticParams` can be exported.
 */
export function generateStaticParams() {
  return Array.from({ length: 256 }, (_, i) => ({ uid: String(i) }));
}

export default function Page() {
  return <View />;
}
