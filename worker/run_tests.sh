#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# run_tests.sh — Run DocMS worker test suite with coverage
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  DocMS Worker — Test Suite${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"

# ── 1. Check / install dependencies ──────────────────────────
echo -e "\n${YELLOW}[1/4] Checking dependencies...${NC}"

REQUIRED_PKGS=(
    pytest
    pytest-asyncio
    pytest-cov
    pytest-mock
    httpx
    elasticsearch
    temporalio
)

MISSING=()
for pkg in "${REQUIRED_PKGS[@]}"; do
    python3 -c "import $(echo "$pkg" | tr '-' '_')" 2>/dev/null || MISSING+=("$pkg")
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "  Installing missing packages: ${MISSING[*]}"
    pip install "${MISSING[@]}" --break-system-packages --quiet
else
    echo -e "  ${GREEN}All dependencies present.${NC}"
fi

# ── 2. Set default env vars ──────────────────────────────────
echo -e "\n${YELLOW}[2/4] Setting environment...${NC}"
export ELASTICSEARCH_URL="${ELASTICSEARCH_URL:-http://localhost:9200}"
export BACKEND_URL="${BACKEND_URL:-http://localhost:8080}"
export TEMPORAL_HOST="${TEMPORAL_HOST:-localhost:7233}"
echo "  ELASTICSEARCH_URL=$ELASTICSEARCH_URL"
echo "  BACKEND_URL=$BACKEND_URL"
echo "  TEMPORAL_HOST=$TEMPORAL_HOST"

# ── 3. Run tests with coverage ───────────────────────────────
echo -e "\n${YELLOW}[3/4] Running pytest with coverage...${NC}\n"

python3 -m pytest \
    --cov=shared \
    --cov=activities \
    --cov=workflows \
    --cov=worker \
    --cov=run_worker \
    --cov-config=pyproject.toml \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    --cov-report=xml:coverage.xml \
    --cov-branch \
    -v \
    --tb=short \
    "$@"

TEST_EXIT=$?

# ── 4. Summary ───────────────────────────────────────────────
echo -e "\n${CYAN}═══════════════════════════════════════════════${NC}"
if [ $TEST_EXIT -eq 0 ]; then
    echo -e "  ${GREEN}✓ All tests passed${NC}"
else
    echo -e "  ${RED}✗ Some tests failed (exit code: $TEST_EXIT)${NC}"
fi
echo -e "  Coverage report: ${CYAN}htmlcov/index.html${NC}"
echo -e "  XML report:      ${CYAN}coverage.xml${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"

exit $TEST_EXIT
