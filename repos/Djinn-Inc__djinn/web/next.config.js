// Validate contract addresses at build time in production (warn only — fatal when STRICT_ENV_CHECK=1)
if (process.env.NODE_ENV === "production") {
  const addressPattern = /^0x[0-9a-fA-F]{40}$/;
  const required = [
    "NEXT_PUBLIC_USDC_ADDRESS",
    "NEXT_PUBLIC_ESCROW_ADDRESS",
    "NEXT_PUBLIC_SIGNAL_COMMITMENT_ADDRESS",
    "NEXT_PUBLIC_COLLATERAL_ADDRESS",
    "NEXT_PUBLIC_CREDIT_LEDGER_ADDRESS",
    "NEXT_PUBLIC_ACCOUNT_ADDRESS",
  ];
  const strict = process.env.STRICT_ENV_CHECK === "1";
  for (const key of required) {
    const val = process.env[key];
    if (!val || !addressPattern.test(val)) {
      const msg = `${key} is missing or invalid (expected 0x-prefixed 40-hex address, got: ${val || "undefined"})`;
      if (strict) {
        throw new Error(msg);
      }
      console.warn(`[Djinn] WARNING: ${msg}`);
    }
  }
}

// Embed git commit count + short hash at build time for admin version display
const { execSync } = require("child_process");
let gitVersion = "dev";
try {
  const count = execSync("git rev-list --count HEAD", { encoding: "utf8" }).trim();
  const hash = execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  gitVersion = `${count} (${hash})`;
} catch {}

// Switch into static-export mode for IPFS deploys when
// NEXT_BUILD_TARGET=ipfs. Server-only features (headers, middleware,
// API routes) are not used in this build; the resulting `out/`
// directory ships from any static host. See next.config.ipfs.js for
// the comprehensive notes on what's lost in static mode and what
// still needs replacement work.
if (process.env.NEXT_BUILD_TARGET === "ipfs") {
  module.exports = require("./next.config.ipfs.js");
  return;
}

// Returning-user URL aliases. Source list lives in `web/lib/dashboardRedirects.ts`
// (re-stated here so this file stays JS-only for next build). Keep both in sync;
// `dashboardRedirects.test.ts` enforces the contract.
const DASHBOARD_REDIRECTS = [
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

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    NEXT_PUBLIC_GIT_VERSION: gitVersion,
  },
  webpack: (config, { isServer }) => {
    // wagmi / @walletconnect / idb-keyval reference `indexedDB` at
    // module level for wallet-state persistence. During SSR the
    // global doesn't exist and pages crash with ReferenceError.
    // Inject a no-op stub for the server bundle only; the client
    // bundle keeps using the real browser indexedDB at runtime.
    if (isServer) {
      const webpack = require("webpack");
      config.plugins.push(
        new webpack.DefinePlugin({
          "typeof indexedDB": JSON.stringify("undefined"),
        }),
        new webpack.ProvidePlugin({
          indexedDB: require.resolve("./scripts/indexeddb-stub.js"),
        }),
      );
    }
    return config;
  },
  async redirects() {
    return DASHBOARD_REDIRECTS;
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        // CSP is set by middleware.ts — only keep non-CSP security headers here as fallback for static assets
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
