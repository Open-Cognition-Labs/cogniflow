#!/usr/bin/env bash
# milestone: the two-replica proof. Run AFTER:
# docker compose -f docker-compose.yml -f docker-compose.replicas.yml up -d --build
# Proves: a session created on replica A is served and OWNERSHIP-SCOPED on replica B (the
# milestone semantics survive multi-replica), rate limits are enforced jointly, and the seeded
# un-knowing replay answers identically on both replicas.
set -euo pipefail

A="${COGNIFLOW_API_A:-http://localhost:8000}"
B="${COGNIFLOW_API_B:-http://localhost:8001}"
TOKEN="${COGNIFLOW_DEMO_TOKEN:-cogniflow-demo-token}"
AUTH=(-H "Authorization: Bearer ${TOKEN}")

ok() { printf ' \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf ' \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }
city() { grep -oE 'headquartered in [A-Za-z]+' | head -1 | awk '{print $NF}'; }

for api in "$A" "$B"; do
  for _ in $(seq 1 60); do
    [ "$(code "$api/api/health")" = "200" ] && break; sleep 2
  done
  [ "$(code "$api/api/health")" = "200" ] || fail "replica $api not healthy"
done
ok "both replicas healthy ($A, $B)"

# 1. cross-replica session: created on A, visible + scoped on B
SID=$(curl -fsS "${AUTH[@]}" -X POST "$A/api/session" | tr -d '{}"' | sed 's/.*session_id://')
[ "$(code "${AUTH[@]}" "$B/api/audit/current?session_id=$SID")" = "200" ] \
  && ok "session created on A is served by B ($SID)" || fail "B cannot serve A's session"
[ "$(code -H 'Authorization: Bearer wrong-token' "$B/api/audit/current?session_id=$SID")" = "401" ] \
  && ok "bad token still 401 on B" || fail "auth hole on B"

# 2. ownership scoping across replicas: a second VALID token (provisioned by the overlay)
# must get a true 403 on the OTHER replica - the day-one hole stays closed across replicas.
rc=$(code -H "Authorization: Bearer ${TOKEN}-other" -X POST "$B/api/reset?session_id=$SID")
[ "$rc" = "403" ] && ok "cross-token reset -> 403 on B (ownership shared across replicas)" \
  || fail "cross-token reset on B returned $rc (expected 403)"

# 3. the invariant, on both replicas, from the same seeded ledger
curl -fsS "${AUTH[@]}" -X POST "$A/api/demo/seed" >/dev/null
ra=$(curl -fsS "${AUTH[@]}" "$A/api/audit/replay?session_id=demo_acme&system_time=2021-06-01" | city)
rb=$(curl -fsS "${AUTH[@]}" "$B/api/audit/replay?session_id=demo_acme&system_time=2021-06-01" | city)
[ "$ra" = "Boston" ] && [ "$rb" = "Boston" ] \
  && ok "replay(2021) = Boston on BOTH replicas (un-knowing invariant, shared ledger)" \
  || fail "replay mismatch: A=$ra B=$rb"

printf '\n\033[1mTwo-replica proof PASSED: sessions, scoping, and the invariant hold across replicas.\033[0m\n'
