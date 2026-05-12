#!/usr/bin/env bash
#
# Run Djinn Docker integration tests.
#
# Spins up anvil + validator + miner via docker-compose,
# runs the integration test suite, and tears down.
#
# Usage:
#   ./scripts/run_docker_tests.sh
#
# Options:
#   --no-teardown   Keep containers running after tests
#   --no-build      Skip rebuilding images
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

TEARDOWN=true
BUILD_FLAG="--build"

for arg in "$@"; do
  case "$arg" in
    --no-teardown) TEARDOWN=false ;;
    --no-build) BUILD_FLAG="" ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.test.yml"

echo "============================================================"
echo "Djinn Docker Integration Tests"
echo "============================================================"

# Start services
echo ""
echo "Starting services..."
docker compose $COMPOSE_FILES up -d $BUILD_FLAG 2>&1

# Run tests
echo ""
echo "Running integration tests..."
EXIT_CODE=0
python tests/integration/test_docker_e2e.py || EXIT_CODE=$?

# Teardown
if [ "$TEARDOWN" = true ]; then
  echo ""
  echo "Tearing down..."
  docker compose $COMPOSE_FILES down -v 2>&1
fi

echo ""
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "All integration tests passed."
else
  echo "Some integration tests failed (exit code: $EXIT_CODE)."
fi

exit $EXIT_CODE
