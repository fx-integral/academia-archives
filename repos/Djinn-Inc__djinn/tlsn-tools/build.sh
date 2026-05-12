#!/usr/bin/env bash
# Build the Djinn TLSNotary prover and verifier CLI tools.
#
# Usage:
#   ./build.sh          # Build in release mode
#   ./build.sh debug    # Build in debug mode
#
# Output binaries are placed in target/{release,debug}/:
#   - djinn-tlsn-prover
#   - djinn-tlsn-verifier

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-release}"

if [ "$MODE" = "debug" ]; then
    echo "Building TLSNotary tools (debug)..."
    cargo build
else
    echo "Building TLSNotary tools (release)..."
    cargo build --release
fi

echo ""
echo "Build complete. Binaries:"
if [ "$MODE" = "debug" ]; then
    ls -la target/debug/djinn-tlsn-prover target/debug/djinn-tlsn-verifier 2>/dev/null || true
else
    ls -la target/release/djinn-tlsn-prover target/release/djinn-tlsn-verifier 2>/dev/null || true
fi

echo ""
echo "To install system-wide:"
echo "  sudo cp target/${MODE}/djinn-tlsn-{prover,verifier} /usr/local/bin/"
echo ""
echo "Or set environment variables:"
echo "  export TLSN_PROVER_BINARY=$SCRIPT_DIR/target/${MODE}/djinn-tlsn-prover"
echo "  export TLSN_VERIFIER_BINARY=$SCRIPT_DIR/target/${MODE}/djinn-tlsn-verifier"
