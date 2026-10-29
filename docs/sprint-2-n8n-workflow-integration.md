# Sprint 2 — n8n-to-FastAPI workflow integration

Covers `n8n/workflows/core/transaction-ingestion-to-api.json`: a version-controlled
n8n workflow that calls `services/api`'s `POST /api/v1/transactions/import`
endpoint (built in Sprint 1 — see `services/api/README.md`), with explicit
success/validation-error/auth-error/transient-error/timeout paths, bounded
retries, and correlation-ID propagation.

Builds on, and does not change, the database role setup from Sprint 1 — no
grants, schemas, or volumes were touched. See
`docs/pre-production-security-todo.md` for the still-open role-hardening
backlog, which this sprint didn't touch either.

## What the workflow does

```
Webhook (POST /webhook/ingest-transactions)
  -> Generate Correlation Id (propagates one from the caller's body if given, else generates a UUID v4)
  -> Call API Attempt 1
       success (2xx)        -> Success Outcome      -> Respond
       auth error (401/403) -> Auth Error Outcome    -> Respond          (terminal, no retry)
       validation (400/422) -> Validation Error Outcome -> Respond       (terminal, no retry)
       anything else / timeout -> Wait 2s -> Call API Attempt 2 (same branching)
                                                 -> Wait 2s -> Call API Attempt 3 (same branching)
                                                           -> still failing -> Transient Error Outcome (503) -> Respond
```

**Why three separate "Call API Attempt N" nodes instead of one node in a
loop:** an earlier version used a single HTTP Request node with a
Wait-node loop-back (`Check Retry Budget` -> `Wait` -> back to the same
HTTP node). That version **silently hung forever** on this n8n version
(1.70.3) — `putExecutionToWait` was never reliably reached once the graph
had a cycle and a node with multiple incoming edges feeding into it,
and the execution sat in `running` with a null `waitTill` indefinitely,
with no error logged. This was reproduced twice, isolated down to the
cycle itself (a standalone `Webhook -> Wait -> Respond` chain with no
cycle resumed correctly in ~2.3s), and is why the three attempts are
unrolled into a straight-line, acyclic chain instead. Each attempt node
independently references `$('Generate Correlation Id').item.json...` for
the request body/correlation ID (not `$json`, which the HTTP node
overwrites with its own response on every call) and `attempts` is
computed via `$('Call API Attempt N').isExecuted`, not a hand-rolled
counter threaded through item data across a loop.

**Why `neverError: true` + `onError: continueErrorOutput` on the HTTP
node:** `neverError` stops 4xx/5xx *HTTP status codes* from throwing, so
they flow through as normal data (`$json.statusCode`) for the
success/auth/validation branching. `onError: continueErrorOutput` catches
*real* transport failures (DNS/connection refused/timeout) on a second
output, which is wired into the same retry path as a 5xx — a timeout is
exactly the "uncertain request outcome" case that must be retried the
same way.

**Idempotency under retry:** the API's `(organization_id, fingerprint)`
unique constraint (Sprint 1) makes every retry — whether the previous
attempt actually failed server-side, or merely timed out client-side after
succeeding — safe to resend. A duplicate is reported as
`duplicates: 1`/`outcome: "success"`, never a second transaction or alert.
It does add its own `transaction.duplicate_rejected` audit row, which is
the documented policy (every call that touches the system is audited),
not an uncontrolled side effect.

## Importing into a clean local n8n instance

Tested for real against a genuinely fresh n8n container (SQLite-backed, no
volume, never through the setup wizard, attached only to this project's
existing docker network so it could reach the real `api` service) — not
just asserted. The exact commands:

```sh
# 1. Credential: contains the real bearer token, so it is NOT committed.
#    Build it locally from your own .env (gitignored) -- never type the
#    token directly into a command you might paste elsewhere.
cat > /tmp/txn-import-credential.json <<EOF
[
  {
    "id": "txn-import-svc-token",
    "name": "Transaction Import Service Token",
    "type": "httpHeaderAuth",
    "data": { "name": "Authorization", "value": "Bearer $(grep '^N8N_API_SERVICE_TOKEN=' .env | cut -d= -f2)" }
  }
]
EOF

# 2. Copy both files into the target n8n container and import.
docker cp /tmp/txn-import-credential.json <container>:/tmp/credential.json
docker cp n8n/workflows/core/transaction-ingestion-to-api.json <container>:/tmp/workflow.json
docker exec <container> n8n import:credentials --input=/tmp/credential.json
docker exec <container> n8n import:workflow --input=/tmp/workflow.json

# 3. Activate (import always imports inactive) and restart so the webhook registers.
docker exec <container> n8n update:workflow --id=txn-ingest-to-api-wf --active=true
docker restart <container>
```

On **this project's own compose stack**, run the same three CLI commands
inside the `n8n` service (`docker compose exec n8n ...`), using
`/workflows/core/transaction-ingestion-to-api.json` (already bind-mounted
read-only by `docker-compose.yml`) instead of copying the workflow file in.

**If re-importing an update to a workflow that already exists on that
instance**, use `--projectId=<id>` (find it via `n8n user-management:reset
--help`'s sibling commands, or by querying `SELECT id FROM project` in the
n8n schema), not `--userId`. Using `--userId` on an update hits a real bug
in n8n 1.70.3's ownership-conflict check (`checkRelations` in
`commands/import/workflow.js`): with no `id` in the workflow JSON it
matches the wrong row entirely (a TypeORM `where: {id: undefined}` quirk);
even with the correct `id` set, re-importing by `--userId` once the
workflow is owned by a project reports `"already owned by the user...
can't be re-owned by the user"` even when the user is the same, because
the check compares the project's ID against the (absent) `--projectId`
flag, not against the user. `--projectId` avoids this entirely. First-time
import into a brand-new instance with no existing workflows doesn't need
either flag.

## Configuring per environment

- **API URL**: hardcoded in the three "Call API Attempt N" nodes as
  `http://api:8000/api/v1/transactions/import` (the compose service DNS
  name — not a secret, fine to commit). Edit all three if your API is
  reachable elsewhere.
- **Credential**: the `Transaction Import Service Token` HTTP Header Auth
  credential must exist on the target instance with `id:
  "txn-import-svc-token"` for the workflow's node reference to resolve —
  that's exactly what step 1 above creates. The token value itself must
  match the target API's `N8N_API_SERVICE_TOKEN`.
- **Retry timing**: 2 fixed seconds between attempts, 3 attempts total,
  hardcoded in the two Wait nodes. Not currently environment-configurable.

## Running the tests

```sh
# API unit + integration tests (Sprint 1 + the correlation-id addition) --
# needs the local Postgres reachable (docker compose up -d postgres):
cd services/api
pytest

# Workflow integration tests -- needs the full stack up
# (docker compose up -d) and the workflow imported and active:
cd tests/workflow
"../../services/api/.venv/Scripts/python.exe" -m pytest -q   # Windows
# or: ../../services/api/.venv/bin/python -m pytest -q        # macOS/Linux
```

`tests/workflow/conftest.py` seeds and cleans up its own `organizations`
row per test (via `app_runtime`, the same non-superuser role
`services/api` uses) and skips cleanly if Postgres or n8n aren't reachable.

### What's covered automatically (5 tests, all passing)

- Successful import (`outcome: "success"`, `attempts: 1`).
- Above-threshold import creates exactly one `MON-011` alert.
- Duplicate submission: reports `duplicates: 1`, creates no second
  transaction or alert row, confirmed via direct Postgres queries against
  `app.transactions`/`app.alerts`/`app.audit_events`.
- Invalid payload: `422`, `outcome: "validation_error"`, nothing
  persisted.
- Transient error (via a nonexistent `organization_id`, which
  deterministically triggers the API's own FK-violation -> rollback ->
  `503`): exhausts all 3 attempts, `outcome:
  "transient_error_retries_exhausted"`.

### What's verified manually, not automated (and why)

- **Authentication error (401/403)**: verified by temporarily importing a
  credential with a deliberately wrong token, triggering the webhook,
  confirming `outcome: "authentication_error"` with `attempts: 1` (no
  retry), then restoring the correct credential. Not automated because it
  mutates the shared n8n instance's actual stored credential — not safe to
  do as a side effect of a routine test run against a shared local
  instance.
- **Timeout / transport error**: verified by running `docker compose stop
  api`, triggering the webhook (got `getaddrinfo ENOTFOUND api`, routed
  through the same retry path as a 5xx, exhausted after 3 attempts ≈17s),
  then `docker compose start api`. Not automated because stopping a shared
  service container mid-test-run is disruptive to anything else using the
  stack concurrently.

If you need to re-verify either path by hand, the exact commands above are
what was actually run to produce the results in this document — this was
tested, not assumed.

## Known risks / follow-ups

- Retry timing (2s × 2 waits) is fixed; under real transient outages
  (not just this test's deterministic single-request failures) 3 attempts
  over ~4-17s may not be enough headroom — revisit once real failure-rate
  data exists.
- The three-attempt chain is duplicated by hand (three HTTP Request nodes,
  three IF-trios). If a fourth attempt or a different retry count is ever
  needed, consider whether n8n's loop support has matured past the bug
  this sprint hit, rather than hand-duplicating a fourth block.
- `services/api`'s database-role hardening backlog
  (`docs/pre-production-security-todo.md`) is unrelated to this sprint and
  remains open.
