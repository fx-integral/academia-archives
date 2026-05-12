import { NextRequest, NextResponse } from "next/server";
import { storeError } from "@/lib/error-store";

/**
 * POST /api/report-error
 *
 * Canonical user-feedback / error-report writer. The flow is intentionally
 * simple: sanitize the payload, post a GitHub issue using the server's
 * private GITHUB_ERROR_TOKEN, return success only if GitHub actually
 * accepted the issue.
 *
 * Why we don't ship the GitHub token to the validators: validators are run
 * by independent Bittensor operators on subnet 103. A token in the open-
 * source repo would grant `repo` scope on djinn-inc/error-reports to
 * everyone who can `git clone`, including read-access to past reports
 * (which can include wallet addresses + diagnostic data). Centralizing
 * the credential here keeps it private; the validator-side durable queue
 * (v1743) is the off-Vercel fallback for IPFS deploys and operates on a
 * separate, opt-in token only the operator provides.
 *
 * Failure semantics:
 *   - 200: issue created on GitHub.
 *   - 429: client rate-limited (5 reports / IP / minute).
 *   - 503: GITHUB_ERROR_TOKEN unset OR GitHub rejected the post. The
 *          client should fall back to the direct validator path so the
 *          report lands in the validator durable queue instead of
 *          vanishing.
 */

const MAX_BODY_SIZE = 10_000; // 10KB max
const GITHUB_REPO = process.env.ERROR_REPORT_REPO || "djinn-inc/error-reports";
const GITHUB_TOKEN = process.env.GITHUB_ERROR_TOKEN || "";

// Simple in-memory rate limiter: max 5 reports per IP per minute
const rateLimitMap = new Map<string, number[]>();
const RATE_LIMIT_WINDOW = 60 * 1000; // 1 min
const RATE_LIMIT_MAX = 5;

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const timestamps = rateLimitMap.get(ip) || [];
  const recent = timestamps.filter((t) => now - t < RATE_LIMIT_WINDOW);
  if (recent.length >= RATE_LIMIT_MAX) return true;
  recent.push(now);
  rateLimitMap.set(ip, recent);
  // Evict old entries
  if (rateLimitMap.size > 1000) {
    for (const [key, ts] of rateLimitMap) {
      if (ts.every((t) => now - t > RATE_LIMIT_WINDOW)) rateLimitMap.delete(key);
    }
  }
  return false;
}

function getIp(request: NextRequest): string {
  if (request.ip) return request.ip;
  const realIp = request.headers.get("x-real-ip");
  if (realIp) return realIp;
  const xff = request.headers.get("x-forwarded-for");
  if (xff) {
    const parts = xff.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length > 0) return parts[parts.length - 1];
  }
  return "unknown";
}

interface ErrorReport {
  // Required
  message: string;
  // Optional context
  url?: string;
  errorMessage?: string;
  errorStack?: string;
  userAgent?: string;
  wallet?: string; // first 6 + last 4 chars only
  signalId?: string;
  consoleErrors?: string[];
  timestamp?: string;
  source?: "error-boundary" | "report-button" | "api-error" | "other";
}

export async function POST(request: NextRequest) {
  const ip = getIp(request);
  if (isRateLimited(ip)) {
    return NextResponse.json(
      { error: "Too many error reports. Please try again later." },
      { status: 429 },
    );
  }

  let body: ErrorReport;
  try {
    const text = await request.text();
    if (text.length > MAX_BODY_SIZE) {
      return NextResponse.json(
        { error: "Report too large" },
        { status: 413 },
      );
    }
    body = JSON.parse(text);
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON" },
      { status: 400 },
    );
  }

  if (!body.message || typeof body.message !== "string" || body.message.length > 2000) {
    return NextResponse.json(
      { error: "message is required (max 2000 chars)" },
      { status: 400 },
    );
  }

  // Sanitize: truncate fields
  const report = {
    message: body.message.slice(0, 2000),
    url: (body.url || "").slice(0, 500),
    errorMessage: (body.errorMessage || "").slice(0, 1000),
    errorStack: (body.errorStack || "").slice(0, 2000),
    userAgent: (body.userAgent || "").slice(0, 300),
    wallet: (body.wallet || "").slice(0, 14), // already truncated client-side
    signalId: (body.signalId || "").slice(0, 100),
    consoleErrors: (body.consoleErrors || []).slice(0, 5).map((e) => String(e).slice(0, 500)),
    source: body.source || "other",
    timestamp: new Date().toISOString(),
    ip: ip.slice(0, 45), // truncated for privacy
  };

  // Mirror the report into the admin in-memory store for the dashboard.
  // Best-effort, non-blocking — never the reason we'd return 503.
  storeError(report);

  if (!GITHUB_TOKEN) {
    return NextResponse.json(
      {
        ok: false,
        forwarded: false,
        error: "GITHUB_ERROR_TOKEN not configured on this server",
      },
      { status: 503 },
    );
  }

  const githubResult = await postGitHubIssue(report);
  if (!githubResult.ok) {
    console.error(
      "[report-error] GitHub issue create failed:",
      githubResult.status,
      githubResult.detail,
    );
    return NextResponse.json(
      {
        ok: false,
        forwarded: false,
        error: `GitHub forward failed (${githubResult.status})`,
      },
      { status: 503 },
    );
  }

  return NextResponse.json({
    ok: true,
    forwarded: true,
    issue_number: githubResult.issueNumber,
  });
}

async function postGitHubIssue(
  report: Record<string, unknown>,
): Promise<{ ok: true; issueNumber: number | null } | { ok: false; status: number | string; detail: string }> {
  const title = `[User Report] ${(report.message as string).slice(0, 80)}`;
  const body = [
    `## Error Report`,
    ``,
    `**Message:** ${report.message}`,
    `**Source:** ${report.source}`,
    `**Page:** ${report.url || "N/A"}`,
    `**Time:** ${report.timestamp}`,
    report.wallet ? `**Wallet:** \`${report.wallet}\`` : "",
    report.signalId ? `**Signal:** \`${report.signalId}\`` : "",
    ``,
    report.errorMessage ? `### Error\n\`\`\`\n${report.errorMessage}\n\`\`\`` : "",
    report.errorStack ? `### Stack Trace\n\`\`\`\n${report.errorStack}\n\`\`\`` : "",
    (report.consoleErrors as string[])?.length
      ? `### Recent Console Errors\n\`\`\`\n${(report.consoleErrors as string[]).join("\n")}\n\`\`\``
      : "",
    ``,
    `### Environment`,
    `\`\`\``,
    `User-Agent: ${report.userAgent || "N/A"}`,
    `\`\`\``,
    ``,
    `---`,
    `*Submitted via djinn.gg error reporter*`,
  ]
    .filter(Boolean)
    .join("\n");

  const labels = ["user-report"];
  if (report.source === "error-boundary") labels.push("crash");

  try {
    const resp = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/issues`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({ title, body, labels }),
      signal: AbortSignal.timeout(10_000),
    });
    if (resp.status === 201) {
      let issueNumber: number | null = null;
      try {
        const j = (await resp.json()) as { number?: number };
        if (typeof j.number === "number") issueNumber = j.number;
      } catch {
        // Body parse failures don't invalidate the 201 — issue still created.
      }
      return { ok: true, issueNumber };
    }
    const text = await resp.text().catch(() => "");
    return { ok: false, status: resp.status, detail: text.slice(0, 200) };
  } catch (err) {
    return {
      ok: false,
      status: "network",
      detail: err instanceof Error ? err.message.slice(0, 200) : String(err).slice(0, 200),
    };
  }
}
