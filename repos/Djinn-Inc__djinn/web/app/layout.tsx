import type { Metadata, Viewport } from "next";
import { Inter, Cinzel } from "next/font/google";
import { Analytics } from "@vercel/analytics/react";
import Providers from "./providers";
import Layout from "@/components/Layout";

import ServiceWorker from "@/components/ServiceWorker";
import "./globals.css";

// `<Analytics />` injects `/_vercel/insights/script.js`. Vercel's edge
// rewrites that path to a real script on Vercel infra; off-Vercel
// (CI/localhost/IPFS/self-host) it 404s as HTML, which trips strict
// MIME checks and pollutes console.error in E2E tests. Only render when
// we're actually deployed to Vercel.
const isOnVercel = !!process.env.VERCEL;

const inter = Inter({ subsets: ["latin"] });
const cinzel = Cinzel({
  subsets: ["latin"],
  variable: "--font-wordmark",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export const metadata: Metadata = {
  title: "Djinn | Sports Intelligence Marketplace",
  description:
    "Analysts sell encrypted predictions. Buyers purchase access. Signals stay secret forever. Track records are cryptographically verifiable. Built on Bittensor Subnet 103, settled in USDC on Base.",
  manifest: "/manifest.json",
  themeColor: "#0f172a",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "16x16 32x32 48x48" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
  openGraph: {
    title: "Djinn | Sports Intelligence Marketplace",
    description:
      "Unbundling information from execution. Encrypted predictions, verifiable track records, settled in USDC on Base.",
    siteName: "Djinn",
    images: [
      {
        url: "https://djinn.gg/icon-512.png",
        width: 512,
        height: 512,
        alt: "Djinn Protocol",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Djinn | Sports Intelligence Marketplace",
    description:
      "Unbundling information from execution. Encrypted predictions, verifiable track records, settled in USDC on Base.",
    images: ["https://djinn.gg/icon-512.png"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} ${cinzel.variable}`}>
        {isOnVercel ? <Analytics /> : null}
        <ServiceWorker />
        <Providers>
          <Layout>{children}</Layout>
        </Providers>
      </body>
    </html>
  );
}
