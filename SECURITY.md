# Security

**Honest claim: Cogniflow's API has _baseline_ security - it is safe to run in a _trusted
environment_. It is NOT enterprise-ready.** This document states exactly what is and is not
protected, so the boundary is never oversold.

## What the security baseline provides (the floor: "not dangerous to run")

The Playground API (`cogniflow-api/main.py`) previously had no authentication - any caller who
could reach the port could read or wipe any session's graph. That day-one hole is closed:

- **Bearer-token auth.** Set `COGNIFLOW_API_TOKENS=tok1,tok2`. Every route except `/api/health`
  then requires `Authorization: Bearer <tok>`; a missing/invalid token is `401`. Fail-loud: with
  tokens set, the API is never silently open.
- **Token-scoped session access.** A session is owned by the token that created it, and **only
  that token can read or reset it** (`403` otherwise). A caller cannot supply another tenant's
  `session_id` to read or wipe their graph. `session_id` is format-validated (`[A-Za-z0-9_-]{1,64}`).
- **Rate limiting.** `COGNIFLOW_RATE_LIMIT_PER_MIN` (default 30) per token/IP on the endpoints
  that spend LLM/embedder money (`/api/ingest`, `/api/ingest-text`, `/api/context`, `/api/answer`).
  A burst is throttled (`429`), not a cost/availability bomb.
- **Upload limits.** `COGNIFLOW_MAX_UPLOAD_BYTES` (default 10 MB) + a MIME/extension allowlist
  (`.pdf/.md/.markdown/.txt`), enforced **before** the file is processed (`413`/`415`).
- **Bind guidance.** Loopback (`127.0.0.1`) by default. Set `COGNIFLOW_BIND_HOST` to expose
  off-host; the server **refuses to start** unauthenticated on a non-loopback interface unless
  `COGNIFLOW_ALLOW_OPEN=1` is set (understood-risk dev override).
- **Secret hygiene.** Session-supplied provider keys are **redacted in API responses** (never
  echoed) and are not logged.

### Open (dev) mode
With no `COGNIFLOW_API_TOKENS` set, the API runs **unauthenticated** and logs a loud startup
warning. This is acceptable **only on loopback for local development**. Do not expose an open
API beyond localhost (the server refuses to, per the bind guard above).

## What is explicitly NOT covered

Do not read "baseline security" as "enterprise-ready." These are deliberately out of scope:

- **RBAC / roles / permissions / scopes** beyond a token owning the sessions it creates.
- **Access-audit logging** (who read/wrote what, with principal + IP). Note: the "audit" in this
  product is *bi-temporal belief replay*, a different thing from security access logging.
- **Hardened multi-tenant isolation guarantees.** FalkorDB gives each group its own physical
  graph, but the isolation claim is not audited/certified.
- **Provider-key handling at rest.** Session-supplied keys are held in process memory (redacted
  in responses, not logged/persisted) for the session lifetime. There is no secret-store/KMS
  integration; a hostile operator with process access could read them.
- **GDPR/CCPA deletion, retention, legal hold.** The append-only bi-temporal ledger conflicts
  with record-level erasure - a real architectural item, not a config flag.
- **SOC2 / compliance posture** and full **observability** (tracing; only a `/metrics`
  counter floor exists).
- **Horizontal scale is now partially addressed, honestly scoped:** with
  `COGNIFLOW_SHARED_STATE=1`, session ownership/config and rate limits live in Redis and the
  write-back journal is shared (`RedisJournal`), proven by a two-replica test
  (`scripts/two_replica_proof.sh`). That makes the shell *production-deployable* behind a load
  balancer - it is still not HA-audited, not k8s-packaged, and not "enterprise."

## Operator checklist before exposing beyond localhost

1. **Rotate any credentials that have ever been shared** (chat logs, screenshots, tickets):
   revoke and reissue provider keys on the provider dashboard, then update `.env`.
2. Set `COGNIFLOW_API_TOKENS` to strong random tokens; distribute them to trusted clients only.
3. Set `COGNIFLOW_CORS_ORIGINS` to your exact web origin(s).
4. Terminate TLS in front of the API (this server speaks plain HTTP); put it behind a
   reverse proxy / gateway and a network boundary (firewall/VPC).
5. Treat this as **trusted-environment** software until the enterprise-roadmap controls land.

## Reporting

For a suspected vulnerability, open a private report to the maintainer rather than a public
issue.
