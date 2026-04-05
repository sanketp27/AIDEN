#!/usr/bin/env bash
# run_tests.sh — execute the full AIDEN test suite with coverage report
# Usage: ./run_tests.sh [--fast]   (--fast skips coverage for quick iteration)

set -euo pipefail
cd "$(dirname "$0")"

# Activate virtual environment if present
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

echo "════════════════════════════════════════"
echo " AIDEN Test Suite"
echo "════════════════════════════════════════"

FAST_MODE=false
if [[ "${1:-}" == "--fast" ]]; then
  FAST_MODE=true
  echo "Mode: fast (no coverage)"
else
  echo "Mode: full (with coverage)"
fi

if $FAST_MODE; then
  pytest \
    tests/ \
    -v \
    --tb=short \
    --no-header \
    -q
else
  pytest \
    tests/ \
    -v \
    --tb=short \
    --no-header \
    --cov=src \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    --cov-fail-under=60
fi

echo ""
echo "════════════════════════════════════════"
echo " All tests passed ✓"
if ! $FAST_MODE; then
  echo " Coverage report: htmlcov/index.html"
fi
echo "════════════════════════════════════════"
