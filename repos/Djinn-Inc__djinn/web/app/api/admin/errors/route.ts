import { NextRequest, NextResponse } from "next/server";
import { verifyAdminRequest } from "@/lib/admin-auth";
import { getErrors } from "@/lib/error-store";
import { DEFAULT_BOOTSTRAP } from "@/lib/validatorDiscovery";

/**
 * GET /api/admin/errors?limit=50
 *
 * Returns recent error reports from the in-memory ring buffer.
 * Protected by admin session cookie (set via POST /api/admin/auth).
 *
 * Sprint-A Stage A-3: when VALIDATOR_ADMIN_API_KEY is set, forward the
 * request to the bootstrap validator's /v1/report-error/recent (which
 * holds the canonical ring buffer since v1345 wired /api/report-error to
 * forward there first). Falls back to the Vercel-local store if the
 * validator is unreachable or the key is unset, so operators still see
 * whatever the fallback path collected during a validator outage.
 */

const VALIDATOR_TIMEOUT_MS = 5_000;

async function tryValidator(limit: number): Promise<Response | null> {
  const adminKey = process.env.VALIDATOR_ADMIN_API_KEY;
  if (!adminKey) return null;
  try {
    const resp = await fetch(
      `${DEFAULT_BOOTSTRAP}/v1/report-error/recent?limit=${limit}`,
      {
        headers: {
          authorization: `Bearer ${adminKey}`,
          accept: "application/json",
        },
        signal: AbortSignal.timeout(VALIDATOR_TIMEOUT_MS),
      },
    );
    if (resp.ok) return resp;
  } catch {
    // Fall through to local store.
  }
  return null;
}

export async function GET(request: NextRequest) {
  if (!(await verifyAdminRequest(request))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 200);

  const validatorResp = await tryValidator(limit);
  if (validatorResp) {
    const body = await validatorResp.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "x-djinn-source": "validator",
      },
    });
  }

  const result = getErrors(limit);
  return NextResponse.json(result, {
    headers: { "x-djinn-source": "vercel-local" },
  });
}
