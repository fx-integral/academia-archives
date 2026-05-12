// Static export build target for IPFS deployment.
//
// Used by `pnpm build:ipfs`. Produces a fully static `out/` directory
// that can be pinned to IPFS and served from any gateway. The whole
// app runs purely in the browser; there is no Vercel, no Next.js
// server, no Djinn-operated API in the data path.
//
// What's different from next.config.js (server build):
//
// - output: "export" — generate a static site
// - No headers() (only works in server mode)
// - No middleware (must be removed at build time too)
// - No /api/* routes (handled by middleware exclusion below)
// - trailingSlash: true so IPFS gateways serve directories cleanly
// - Asset prefix can be set via NEXT_PUBLIC_IPFS_BASE for ipfs:// URLs
//
// What's lost in static mode and must be replaced by direct client calls:
//
// - /api/idiot/browse → fetch directly from a validator's
//   /v1/network/signals (or the subgraph)
// - /api/network/status → fetch directly from /api/validators/discover
//   replacement (calls validator metagraph endpoints)
// - /api/odds → fetch directly from validator /v1/odds/canonical (when
//   the canonical odds flag is on across the network)
// - /api/auth/* → static mode has no server session, must use wallet
//   signature challenges client-side
//
// Until those replacements are done, static mode will be partial. The
// goal of THIS commit is to lock in the build target so the migration
// is incremental and visible.

const { execSync } = require("child_process");
let gitVersion = "dev";
try {
  const count = execSync("git rev-list --count HEAD", { encoding: "utf8" }).trim();
  const hash = execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  gitVersion = `${count} (${hash})`;
} catch {}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  distDir: ".next-ipfs",
  images: {
    unoptimized: true, // export does not support the image optimizer
  },
  env: {
    NEXT_PUBLIC_GIT_VERSION: gitVersion,
    NEXT_PUBLIC_BUILD_TARGET: "ipfs",
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  webpack: (config, { isServer }) => {
    // wagmi / walletconnect imports indexedDB at module level for
    // wallet-state persistence, which doesn't exist in Node during
    // static prerender. For server-side compilation in IPFS export
    // mode, alias the offending modules to a no-op stub. Client-side
    // bundle still uses the real ones, so wallet works at runtime in
    // the browser.
    if (isServer) {
      config.resolve.alias = {
        ...(config.resolve.alias || {}),
        // Replace the storage adapters that read indexedDB at import
        // time. wagmi falls back to no-op when these resolve to a
        // stub object.
        "@wagmi/core/connectors": false,
      };
      // Provide an indexedDB global so modules that reference it
      // unconditionally see a no-op object instead of crashing.
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
};

module.exports = nextConfig;
