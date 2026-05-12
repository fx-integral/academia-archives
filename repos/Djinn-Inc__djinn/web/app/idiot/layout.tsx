import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Buyer Dashboard | Djinn",
  description:
    "Browse and purchase encrypted sports predictions from top analysts. Manage your escrow balance and view signal history.",
  openGraph: {
    title: "Buyer Dashboard | Djinn",
    description:
      "Purchase encrypted sports predictions from verified analysts on Djinn.",
  },
};

export default function IdiotLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
