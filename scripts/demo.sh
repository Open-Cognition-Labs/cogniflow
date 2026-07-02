#!/usr/bin/env bash
# Cogniflow 60-second proof. Run AFTER `docker compose up` (or any running API).
#
# bash scripts/demo.sh
#
# Seeds the Acme HQ bitemporal scenario, then asks the four questions and CHECKS the answers.
# Key-free: uses the read-only audit endpoints (no LLM, no embeddings) - the seeded-hero property.
# Carries the milestone bearer token, so it runs against the secure-by-default API, not an open one.
set -euo pipefail

API="${COGNIFLOW_API_URL:-http://localhost:8000}"
TOKEN="${COGNIFLOW_DEMO_TOKEN:-cogniflow-demo-token}"
SID="demo_acme"
AUTH=(-H "Authorization: Bearer ${TOKEN}")

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok() { printf ' \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf ' \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
# extract the HQ city from an audit response's belief statement(s)
city() { grep -oE 'headquartered in [A-Za-z]+' | head -1 | awk '{print $NF}'; }

bold "Waiting for the API at ${API} ..."
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "${API}/api/health" 2>/dev/null || true)" = "200" ] && break
  sleep 2
done
[ "$(curl -s -o /dev/null -w '%{http_code}' "${API}/api/health" 2>/dev/null || true)" = "200" ] \
  || fail "API not reachable at ${API} - is 'docker compose up -d' running and healthy?"
ok "API is up"

bold "Seeding the Acme HQ scenario (2019 filing: Boston -> 2022 filing: Denver)"
curl -fsS "${AUTH[@]}" -X POST "${API}/api/demo/seed" >/dev/null || fail "seed failed (token wrong? try COGNIFLOW_DEMO_TOKEN)"

bold "Q1 Where is Acme HQ *now*? (event-time)"
now=$(curl -fsS "${AUTH[@]}" "${API}/api/audit/current?session_id=${SID}" | city)
[ "${now}" = "Denver" ] && ok "now = Denver" || fail "now = ${now:-<none>} (expected Denver)"

bold "Q2 Where was Acme HQ *in 2020*? (event-time, as of 2020)"
y2020=$(curl -fsS "${AUTH[@]}" "${API}/api/audit/event?session_id=${SID}&as_of=2020-06-01" | city)
[ "${y2020}" = "Boston" ] && ok "2020 = Boston" || fail "2020 = ${y2020:-<none>} (expected Boston)"

bold "Q3 What did the system *believe in 2021*, before the 2022 filing? << SYSTEM-TIME REPLAY"
s2021=$(curl -fsS "${AUTH[@]}" "${API}/api/audit/replay?session_id=${SID}&system_time=2021-06-01" | city)
[ "${s2021}" = "Boston" ] && ok "replay(2021) = Boston (the 2022 Denver correction is un-known)" \
  || fail "replay(2021) = ${s2021:-<none>} (expected Boston)"

bold "Q4 Provenance + timeline for the Boston belief"
tl=$(curl -fsS "${AUTH[@]}" "${API}/api/audit/timeline/demo-belief-boston?session_id=${SID}")
echo "${tl}" | grep -q "2019 annual report" && ok "Boston sourced to the 2019 annual report" \
  || fail "timeline missing the 2019 source"
echo "${tl}" | grep -q "2022 press release" && ok "superseded by the 2022 press release" \
  || fail "timeline missing the superseding 2022 source"

bold "Proof: now=Denver, 2020=Boston, replay(2021)=Boston."
echo "Q3 is the one a plain (or valid-time-only) RAG cannot answer: replaying to before the"
echo "correction returns what was believed then, without leaking the later Denver fact backward."
echo "Open the live scrubber at http://localhost:3000/playground"
