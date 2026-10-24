#!/bin/sh
# Smoke test for a running printarr. Checks the things a broken upgrade would break.
#
#   scripts/smoke-test.sh [base-url]        default http://localhost:8000
#
# Needs curl. Creates one held ticket, reads it back, and checks the export.
# The held ticket never prints, so a printer that is not connected does not matter here.
# Exit status is 0 when every check passes, 1 otherwise.
set -u

base="${1:-http://localhost:8000}"
failures=0
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

check() {
    name=$1
    shift
    if "$@" >/dev/null 2>&1; then
        echo "ok    $name"
    else
        echo "FAIL  $name"
        failures=$((failures + 1))
    fi
}

check "liveness /healthz" curl -fsS "$base/healthz"

# The health endpoint returns 503 when the printer is unplugged. That is reported, not failed.
health_code=$(curl -s -o "$tmp" -w '%{http_code}' "$base/api/v1/health")
case "$health_code" in
    200) echo "ok    health /api/v1/health (printer and database up)" ;;
    503) echo "note  health /api/v1/health is 503: $(cat "$tmp")" ;;
    *)   echo "FAIL  health /api/v1/health returned $health_code"; failures=$((failures + 1)) ;;
esac

ticket=$(curl -fsS -X POST "$base/api/v1/tickets" \
    -H 'Content-Type: application/json' \
    -d '{"recipient":"yannic","sender":"smoke-test","title":"Smoke test","message":"Held, never printed","hold":true}' \
    2>/dev/null) || ticket=""
ticket_id=$(printf '%s' "$ticket" | sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' | head -n 1)
check "create a held ticket" test -n "$ticket_id"
check "read the ticket back" curl -fsS "$base/api/v1/tickets/$ticket_id"
check "the held ticket is held, not printed" sh -c "curl -fsS '$base/api/v1/tickets/$ticket_id' | grep -q '\"status\": *\"held\"'"

curl -fsS -o "$tmp" "$base/api/v1/backup/export" 2>/dev/null
check "export is an SQLite database" sh -c "head -c 15 '$tmp' | grep -q 'SQLite format 3'"

if [ "$failures" -eq 0 ]; then
    echo "smoke test passed"
    exit 0
fi
echo "smoke test FAILED: $failures check(s)"
exit 1
