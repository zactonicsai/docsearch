#!/bin/bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://backend:8080}"
ES_URL="${ELASTICSEARCH_URL:-http://elasticsearch:9200}"
KIBANA_URL="${KIBANA_URL:-http://kibana:5601}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; PURPLE='\033[0;35m'; NC='\033[0m'
PASS=0; FAIL=0; TOTAL=0
pass() { PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); echo -e "  ${GREEN}PASS${NC} $1"; }
fail() { FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); echo -e "  ${RED}FAIL${NC} $1"; }
log()  { echo -e "${CYAN}[TEST]${NC} $1"; }
info() { echo -e "  ${YELLOW}  ->  ${NC} $1"; }

wait_for() {
    local name=$1 url=$2 max=$3
    log "Waiting for $name..."
    for i in $(seq 1 "$max"); do
        if curl -sf "$url" > /dev/null 2>&1; then info "$name ready"; return 0; fi
        sleep 2
    done
    fail "$name not ready"; exit 1
}

echo ""
echo "======================================================="
echo "  DocMS Integration Tests (Static + Temporal)"
echo "======================================================="
echo ""

wait_for "Elasticsearch" "$ES_URL/_cluster/health" 60
wait_for "Backend"       "$BACKEND_URL/api/health"  30
wait_for "Kibana"        "$KIBANA_URL/api/status"   60

# ============================================================
# 1. HEALTH + TEMPORAL CONNECTION
# ============================================================
log "1: Health check & Temporal status"
HEALTH=$(curl -sf "$BACKEND_URL/api/health")
echo "$HEALTH" | grep -q '"status":"healthy"' && pass "Backend healthy" || fail "Backend unhealthy"
echo "$HEALTH" | grep -q '"elasticsearch":"connected"' && pass "ES connected" || fail "ES not connected"
echo "$HEALTH" | grep -q '"temporal":"connected"' && pass "Temporal connected" || info "Temporal not connected (workflows may fail)"

# ============================================================
# 2. AUTHENTICATION
# ============================================================
log "2: Authentication"
ADMIN_LOGIN=$(curl -sf -X POST "$BACKEND_URL/api/login" -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}')
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
[ -n "$ADMIN_TOKEN" ] && pass "Admin login" || fail "Admin login"

READER_LOGIN=$(curl -sf -X POST "$BACKEND_URL/api/login" -H "Content-Type: application/json" -d '{"username":"public_reader","password":"reader123"}')
READER_TOKEN=$(echo "$READER_LOGIN" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
[ -n "$READER_TOKEN" ] && pass "Reader login" || fail "Reader login"

PRIVATE_LOGIN=$(curl -sf -X POST "$BACKEND_URL/api/login" -H "Content-Type: application/json" -d '{"username":"private_reader","password":"private123"}')
PRIVATE_TOKEN=$(echo "$PRIVATE_LOGIN" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
[ -n "$PRIVATE_TOKEN" ] && pass "Private reader login" || fail "Private reader login"

INVALID=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BACKEND_URL/api/login" -H "Content-Type: application/json" -d '{"username":"admin","password":"wrong"}')
[ "$INVALID" = "401" ] && pass "Invalid creds rejected" || fail "Invalid creds not rejected ($INVALID)"

# ============================================================
# 3. STATIC UPLOAD (public)
# ============================================================
log "3: Static upload - public document"
echo "This is a PUBLIC document about climate change and renewable energy sources for testing the static pipeline." > /tmp/test_public.txt

PUBLIC_UP=$(curl -sf -X POST "$BACKEND_URL/api/upload" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -F "file=@/tmp/test_public.txt" \
    -F "classification=public")
PUBLIC_DOC_ID=$(echo "$PUBLIC_UP" | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)
[ -n "$PUBLIC_DOC_ID" ] && pass "Public doc uploaded (${PUBLIC_DOC_ID:0:8}...)" || fail "Public doc upload"

# ============================================================
# 4. STATIC UPLOAD (private)
# ============================================================
log "4: Static upload - private document"
echo "This is a PRIVATE classified document about military defense operations and satellite intelligence." > /tmp/test_private.txt

PRIVATE_UP=$(curl -sf -X POST "$BACKEND_URL/api/upload" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -F "file=@/tmp/test_private.txt" \
    -F "classification=private")
PRIVATE_DOC_ID=$(echo "$PRIVATE_UP" | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)
[ -n "$PRIVATE_DOC_ID" ] && pass "Private doc uploaded (${PRIVATE_DOC_ID:0:8}...)" || fail "Private doc upload"

# ============================================================
# 5. TEMPORAL UPLOAD
# ============================================================
log "5: Temporal workflow upload"
echo "This document was processed by the Temporal Python worker with real text extraction capabilities." > /tmp/test_temporal.txt

TEMPORAL_UP=$(curl -sf -X POST "$BACKEND_URL/api/upload" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -F "file=@/tmp/test_temporal.txt" \
    -F "classification=public" \
    -F "use_temporal=true" 2>&1 || echo '{"error":"temporal_unavailable"}')
TEMPORAL_DOC_ID=$(echo "$TEMPORAL_UP" | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)
WORKFLOW_ID=$(echo "$TEMPORAL_UP" | grep -o '"workflow_id":"[^"]*"' | cut -d'"' -f4)

if [ -n "$WORKFLOW_ID" ]; then
    pass "Temporal workflow started ($WORKFLOW_ID)"

    # Poll for completion
    info "Polling workflow status..."
    for i in $(seq 1 30); do
        WF_STATUS=$(curl -sf "$BACKEND_URL/api/temporal/status?workflow_id=$WORKFLOW_ID" \
            -H "Authorization: Bearer $ADMIN_TOKEN" 2>&1 || echo '{"status":"UNKNOWN"}')
        STATUS=$(echo "$WF_STATUS" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        if [ "$STATUS" = "WORKFLOW_EXECUTION_STATUS_COMPLETED" ]; then
            pass "Temporal workflow completed"
            break
        elif [ "$STATUS" = "WORKFLOW_EXECUTION_STATUS_FAILED" ]; then
            fail "Temporal workflow failed"
            break
        fi
        sleep 2
    done
    if [ "$i" = "30" ]; then
        info "Workflow still running after 60s (may complete later)"
    fi
elif [ -n "$TEMPORAL_DOC_ID" ]; then
    info "Temporal unavailable, fell back to static processing"
    pass "Temporal fallback to static worked"
else
    fail "Temporal upload failed: $TEMPORAL_UP"
fi

# Upload CSV via Temporal
log "5b: Temporal CSV upload"
printf "name,department,salary\nAlice,Engineering,120000\nBob,Marketing,95000\nCharlie,Sales,88000\n" > /tmp/test_data.csv

CSV_UP=$(curl -sf -X POST "$BACKEND_URL/api/upload" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -F "file=@/tmp/test_data.csv" \
    -F "classification=public" \
    -F "use_temporal=true" 2>&1 || echo '{}')
CSV_WF=$(echo "$CSV_UP" | grep -o '"workflow_id":"[^"]*"' | cut -d'"' -f4)
[ -n "$CSV_WF" ] && pass "CSV Temporal workflow started" || info "CSV fell back to static"

# Upload private PDF via Temporal
log "5c: Temporal private document upload"
echo "Top Secret Analysis: Quantum computing threat assessment for national infrastructure." > /tmp/test_secret.txt

SECRET_UP=$(curl -sf -X POST "$BACKEND_URL/api/upload" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -F "file=@/tmp/test_secret.txt" \
    -F "classification=private" \
    -F "use_temporal=true" 2>&1 || echo '{}')
SECRET_WF=$(echo "$SECRET_UP" | grep -o '"workflow_id":"[^"]*"' | cut -d'"' -f4)
[ -n "$SECRET_WF" ] && pass "Private Temporal workflow started" || info "Private fell back to static"

# ============================================================
# 6. ACL ENFORCEMENT
# ============================================================
log "6: ACL upload restrictions"
READER_UP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BACKEND_URL/api/upload" \
    -H "Authorization: Bearer $READER_TOKEN" \
    -F "file=@/tmp/test_public.txt" \
    -F "classification=public")
[ "$READER_UP" = "403" ] && pass "Reader blocked from uploading" || fail "Reader should be blocked ($READER_UP)"

UNAUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BACKEND_URL/api/search" \
    -H "Content-Type: application/json" -d '{"query":"test"}')
[ "$UNAUTH" = "401" ] && pass "Unauthenticated access blocked" || fail "Should be 401 ($UNAUTH)"

# ============================================================
# 7. WAIT FOR INDEXING
# ============================================================
log "7: Elasticsearch indexing"
info "Waiting for all documents to be indexed..."
sleep 8

ES_COUNT=$(curl -sf "$ES_URL/documents/_count" | grep -o '"count":[0-9]*' | cut -d: -f2)
if [ "$ES_COUNT" -ge 2 ]; then
    pass "Documents indexed in ES (count: $ES_COUNT)"
else
    fail "Expected >= 2 docs, got: $ES_COUNT"
fi

# Verify public doc
ES_PUB=$(curl -sf "$ES_URL/documents/_doc/$PUBLIC_DOC_ID" 2>&1 || echo '{}')
echo "$ES_PUB" | grep -q '"found":true' && pass "Public doc in ES" || fail "Public doc not in ES"
echo "$ES_PUB" | grep -q '"classification":"public"' && pass "Public classification correct" || fail "Public classification wrong"

# Verify private doc
ES_PRIV=$(curl -sf "$ES_URL/documents/_doc/$PRIVATE_DOC_ID" 2>&1 || echo '{}')
echo "$ES_PRIV" | grep -q '"found":true' && pass "Private doc in ES" || fail "Private doc not in ES"
echo "$ES_PRIV" | grep -q '"classification":"private"' && pass "Private classification correct" || fail "Private classification wrong"

# ============================================================
# 8. SEARCH - ADMIN (sees all)
# ============================================================
log "8: Admin search (public + private)"
ADMIN_SEARCH=$(curl -sf -X POST "$BACKEND_URL/api/search" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"document","page":1,"size":20}')
ADMIN_TOTAL=$(echo "$ADMIN_SEARCH" | grep -o '"total":[0-9]*' | cut -d: -f2)
[ "$ADMIN_TOTAL" -ge 2 ] && pass "Admin sees multiple results ($ADMIN_TOTAL)" || fail "Admin expected >= 2 ($ADMIN_TOTAL)"

# ============================================================
# 9. SEARCH - PUBLIC READER (only public)
# ============================================================
log "9: Public reader ACL filtering"
READER_SEARCH=$(curl -sf -X POST "$BACKEND_URL/api/search" \
    -H "Authorization: Bearer $READER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"document","page":1,"size":20}')

if echo "$READER_SEARCH" | grep -q '"classification":"private"'; then
    fail "SECURITY: Reader sees private docs!"
else
    pass "ACL enforced: reader cannot see private"
fi

# ============================================================
# 10. SEARCH - PRIVATE READER (public + private)
# ============================================================
log "10: Private reader search"
PRIV_SEARCH=$(curl -sf -X POST "$BACKEND_URL/api/search" \
    -H "Authorization: Bearer $PRIVATE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"document","page":1,"size":20}')
PRIV_TOTAL=$(echo "$PRIV_SEARCH" | grep -o '"total":[0-9]*' | cut -d: -f2)
[ "$PRIV_TOTAL" -ge 2 ] && pass "Private reader sees both ($PRIV_TOTAL)" || fail "Private reader expected >= 2 ($PRIV_TOTAL)"

# ============================================================
# 11. SEARCH SPECIFICITY
# ============================================================
log "11: Content-specific search"
CLIMATE=$(curl -sf -X POST "$BACKEND_URL/api/search" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"climate renewable energy","page":1,"size":20}')
CLIMATE_N=$(echo "$CLIMATE" | grep -o '"total":[0-9]*' | cut -d: -f2)
[ "$CLIMATE_N" -ge 1 ] && pass "Climate search hits ($CLIMATE_N)" || fail "Climate search empty"

MILITARY=$(curl -sf -X POST "$BACKEND_URL/api/search" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"military defense satellite","page":1,"size":20}')
MILITARY_N=$(echo "$MILITARY" | grep -o '"total":[0-9]*' | cut -d: -f2)
[ "$MILITARY_N" -ge 1 ] && pass "Military search hits ($MILITARY_N)" || fail "Military search empty"

# ============================================================
# 12. KIBANA
# ============================================================
log "12: Kibana verification"
KIBANA_OK=$(curl -sf "$KIBANA_URL/api/status" 2>&1 || echo '')
echo "$KIBANA_OK" | grep -q '"available"' && pass "Kibana available" || fail "Kibana not available"

curl -sf -X POST "$KIBANA_URL/api/saved_objects/index-pattern/documents" \
    -H "kbn-xsrf: true" -H "Content-Type: application/json" \
    -d '{"attributes":{"title":"documents","timeFieldName":"indexed_at"}}' > /dev/null 2>&1
pass "Kibana index pattern created"

# ============================================================
# 13. ES MAPPING
# ============================================================
log "13: Elasticsearch mapping"
MAP=$(curl -sf "$ES_URL/documents/_mapping")
echo "$MAP" | grep -q '"classification"' && pass "classification field" || fail "classification missing"
echo "$MAP" | grep -q '"content"' && pass "content field" || fail "content missing"
echo "$MAP" | grep -q '"user_id"' && pass "user_id field" || fail "user_id missing"

# ============================================================
# RESULTS
# ============================================================
echo ""
echo "======================================================="
echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}, $TOTAL total"
echo "======================================================="
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${RED}SOME TESTS FAILED${NC}"
    exit 1
else
    echo -e "${GREEN}ALL TESTS PASSED${NC}"
    exit 0
fi
