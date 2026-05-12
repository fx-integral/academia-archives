// k6 load test against Djinn public API endpoints.
//
// Usage:
//   VERCEL_BYPASS_SECRET=xxx TARGET=https://djinn.gg k6 run scripts/loadtest/k6-api.js
//   TARGET=http://localhost:3000 k6 run scripts/loadtest/k6-api.js
//   # with docker (no local k6 install):
//   docker run --rm -i -e VERCEL_BYPASS_SECRET -e TARGET grafana/k6 run - < scripts/loadtest/k6-api.js
//
// Stages:
//   0-30s     ramp to 100 RPS    (warmup / rate-limit calibration)
//   30-120s   hold 100 RPS       (baseline)
//   120-150s  ramp to 500 RPS    (Cup-traffic estimate)
//   150-240s  hold 500 RPS
//   240-300s  ramp to 1000 RPS   (stress)
//   300-360s  hold 1000 RPS
//   360-390s  ramp to 0
//
// Thresholds (fail the run if breached):
//   http_req_duration p(95) < 1500ms for read endpoints
//   http_req_failed rate < 2%          (some 5xx tolerated near 1000 RPS)
//   checks rate > 98%

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const TARGET = __ENV.TARGET || "https://djinn.gg";
const BYPASS = __ENV.VERCEL_BYPASS_SECRET || "";

const SPORTS = ["basketball_nba", "americanfootball_nfl", "baseball_mlb"];

// Weighted endpoint mix. Hot paths (browse, network/status) get more weight
// because that's what a Cup-day homepage visitor hits; cold paths (odds fetch)
// get less because they're per-signal-creation.
const ENDPOINTS = [
  { path: "/api/health", weight: 5 },
  { path: "/api/idiot/browse", weight: 30 },
  { path: "/api/network/status", weight: 15 },
  { path: "/api/network/config", weight: 5 },
  { path: "/api/validators/discover", weight: 10 },
  { path: "/api/miners/discover", weight: 10 },
  { path: "/api/sports", weight: 5 },
  { path: "/api/odds?sport=basketball_nba", weight: 5 },
  { path: "/api/odds?sport=americanfootball_nfl", weight: 5 },
  { path: "/api/odds?sport=baseball_mlb", weight: 5 },
  { path: "/api/leaderboard", weight: 5 },
];

// Expand weighted list to a flat draw pool.
const POOL = ENDPOINTS.flatMap((e) => Array(e.weight).fill(e.path));

// SMOKE=1 runs a low-volume sanity check (10 RPS for 30s) that won't trip
// Vercel's bot WAF without the bypass secret. Use this to verify the harness
// end-to-end before burning a bypass secret on a real ramp.
const SMOKE = __ENV.SMOKE === "1";

const LOAD_STAGES = [
  { duration: "30s", target: 100 },
  { duration: "90s", target: 100 },
  { duration: "30s", target: 500 },
  { duration: "90s", target: 500 },
  { duration: "60s", target: 1000 },
  { duration: "60s", target: 1000 },
  { duration: "30s", target: 0 },
];

const SMOKE_STAGES = [
  { duration: "10s", target: 10 },
  { duration: "30s", target: 10 },
  { duration: "10s", target: 0 },
];

export const options = {
  scenarios: {
    api_load: {
      executor: "ramping-arrival-rate",
      startRate: SMOKE ? 1 : 10,
      timeUnit: "1s",
      preAllocatedVUs: SMOKE ? 10 : 100,
      maxVUs: SMOKE ? 50 : 2000,
      stages: SMOKE ? SMOKE_STAGES : LOAD_STAGES,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.02"],
    "http_req_duration{scope:read}": ["p(95)<1500"],
    checks: ["rate>0.98"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

const errors = new Rate("errors_total");
const byEndpoint = new Trend("latency_by_endpoint", true);

export default function () {
  const path = POOL[Math.floor(Math.random() * POOL.length)];
  const url = `${TARGET}${path}`;

  const headers = {
    "User-Agent": "djinn-k6-load/1.0",
    Accept: "application/json",
  };
  if (BYPASS) {
    headers["x-vercel-protection-bypass"] = BYPASS;
    headers["x-vercel-set-bypass-cookie"] = "samesitenone";
  }

  const res = http.get(url, {
    headers,
    tags: { scope: "read", endpoint: path.split("?")[0] },
  });

  const ok = check(res, {
    "status is 2xx or 304": (r) => r.status === 304 || (r.status >= 200 && r.status < 300),
    "has response body": (r) => r.body && r.body.length > 0,
    "no vercel challenge": (r) => !String(r.body).includes("Vercel Security Checkpoint"),
  });

  if (!ok) errors.add(1);
  byEndpoint.add(res.timings.duration, { endpoint: path.split("?")[0] });
}

export function handleSummary(data) {
  const stdout =
    `\n=== Djinn API load summary ===\n` +
    `  target: ${TARGET}\n` +
    `  bypass_header: ${BYPASS ? "set" : "UNSET (expect Vercel challenges)"}\n` +
    `  total requests: ${data.metrics.http_reqs.values.count}\n` +
    `  req/s avg: ${data.metrics.http_reqs.values.rate.toFixed(1)}\n` +
    `  error rate: ${(data.metrics.http_req_failed.values.rate * 100).toFixed(2)}%\n` +
    `  duration p50: ${data.metrics.http_req_duration.values.med.toFixed(0)}ms\n` +
    `  duration p95: ${data.metrics.http_req_duration.values["p(95)"].toFixed(0)}ms\n` +
    `  duration p99: ${data.metrics.http_req_duration.values["p(99)"].toFixed(0)}ms\n` +
    `  max: ${data.metrics.http_req_duration.values.max.toFixed(0)}ms\n` +
    `\n  (thresholds enforce p95<1500ms, error<2%, check-pass>98%)\n\n`;
  return { stdout, "scripts/loadtest/last-run-summary.json": JSON.stringify(data, null, 2) };
}
