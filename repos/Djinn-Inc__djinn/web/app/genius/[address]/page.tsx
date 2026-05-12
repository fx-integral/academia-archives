import View from "./view";

// Addresses are unbounded, so we cannot enumerate every possible Genius
// at build time. Returning [] keeps the static-export build happy; the
// SSR (Vercel) build serves these on demand.
export function generateStaticParams() {
  return [];
}

export const dynamicParams = true;

export default function Page() {
  return <View />;
}
