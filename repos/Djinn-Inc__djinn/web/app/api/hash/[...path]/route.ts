import { NextRequest, NextResponse } from "next/server";
import { createHash } from "crypto";

/**
 * GET /hash/<anything>
 *
 * Returns the SHA-256 hash of the path. The content is deterministic:
 * anyone who knows the path can compute the expected hash. Used for
 * TLSNotary nonce challenges where the validator needs to verify that
 * the proof contains the correct content without trusting the prover.
 *
 * Sprint-A Stage A-3: mirrored on each validator at `/v1/hash/{path}`
 * (see `validator/djinn_validator/api/server.py`). Keeping this Next
 * route alive gives TLSN provers a stable djinn.gg endpoint during
 * the cutover; once every validator runs v1345+ the protocol can
 * switch challenge URLs to the validator mirror without coordinated
 * downtime on djinn.gg.
 *
 * Example:
 *   GET /hash/djinn-nonce-a1b2c3d4
 *   -> { "input": "djinn-nonce-a1b2c3d4", "sha256": "e3b0c44..." }
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const input = path.join("/");
  const hash = createHash("sha256").update(input).digest("hex");
  return NextResponse.json(
    { input, sha256: hash },
    {
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    },
  );
}
