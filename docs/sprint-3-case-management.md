# Sprint 3 — Investigation case management

Adds `investigation_cases`, `case_history`, `case_transactions`, and
`case_evidence` tables plus CAS-061..065 endpoints, built on Sprint 1/2's
transaction/alert pipeline and n8n workflow. No database roles, grants, or
volumes were touched — migrations are scoped to the `app` schema exactly
like Sprint 1's, applied via `app_runtime` (never `app_rw`, never n8n's
schema).

## Why a placeholder analyst-auth layer exists now

Sprint 3 needs "authorization" and "organization isolation enforced
against the authenticated principal" to mean something, but no identity
provider decision has been made yet (plan.md §7.2) and no `users` table
exists (plan.md §2 called for one; it was never built in Sprint 1 or 2).
Rather than block case management on that unresolved decision, this sprint
adds a **second, explicitly temporary** actor kind alongside the existing
service token:

- **service** (unchanged from Sprint 1/2): the static `N8N_API_SERVICE_TOKEN`
  bearer, used by n8n. No organization of its own.
- **analyst** (new): an HS256 JWT signed with a new `API_JWT_SECRET`,
  carrying `sub` (analyst id), `org` (organization_id), `role` ("analyst"
  | "lead"). There is **no real identity provider, no user directory, no
  key rotation, no revocation** behind this — see
  `docs/pre-production-security-todo.md`, which now tracks this
  explicitly as a new pre-production item. Mint one locally with
  `scripts/mint_dev_token.py --org <uuid> --role analyst`.

**What this buys you today:** every case-mutating endpoint requires a
valid analyst token, and every lookup/mutation is scoped to that token's
`org` claim server-side — a client cannot supply an `organization_id` and
have it trusted; cross-organization references are rejected and return
404 (not 403), so a caller can't distinguish "exists in another org" from
"doesn't exist" (standard practice against enumeration).

**What this doesn't buy you:** there's no way to verify a `sub`/`role`
claim is honest, because nothing issues or vouches for these tokens except
a shared secret anyone with API access to mint a token could forge if they
had the secret. This is explicitly a placeholder, flagged the same way
`require_service_token` already was in Sprint 1.

## Authorization rules actually implemented

**CAS-062 (assign/reassign)** -- no user directory exists, so this is
claim-based (who the JWT says you are), not validated against a real
roster:
- Unassigned case: any analyst in the case's organization may claim it for
  themselves. Assigning it to *someone else* while unassigned requires the
  `lead` role.
- Already-assigned case: only `lead`, or the analyst it's currently
  assigned to (releasing/reassigning their own case), may change it. A
  plain analyst cannot take over another analyst's active case.

**CAS-063 (status transitions)** -- validated against a fixed graph
(`app/services/cases.py::ALLOWED_TRANSITIONS`):
```
open -> in_progress | escalated | closed
in_progress -> escalated | closed
escalated -> closed
closed -> (terminal, nothing)
```
An illegal transition (including anything backwards, or anything from
`closed`) returns `409`, not `422` -- it's a state conflict, not a
malformed request.

**Human accountability (plan.md §0/§6):** the n8n service actor may only
call `POST /api/v1/cases` (CAS-061, case *creation*). Every other case
endpoint (`assign`, `status`, `transactions`, `evidence`, `history`)
requires `get_current_analyst` specifically and explicitly rejects the
service token with `401`. The automated workflow can open a case; it can
never assign, transition, close, or otherwise act on one.

## Idempotency and validated relationships

- `investigation_cases` has `UNIQUE(organization_id, alert_id)` -- CAS-061
  is idempotent at the DB level (`INSERT ... ON CONFLICT DO NOTHING`, same
  pattern as Sprint 1's transaction ingestion), not just in application
  code. Calling it twice for the same alert returns the *existing* case
  both times; a different `priority` on the second call is ignored.
- `case_transactions` has `UNIQUE(case_id, transaction_id)` -- linking the
  same transaction twice reports `linked: false` on the second call rather
  than erroring or duplicating.
- Every alert/transaction lookup used to create a case or link a
  transaction is scoped to the acting principal's organization (or, for
  the service actor, to the alert's own organization, since the service
  actor has none). A reference into another organization is rejected as
  not found, never partially trusted.

## Workflow integration (extends, doesn't replace, Sprint 2's workflow)

`n8n/workflows/core/transaction-ingestion-to-api.json`'s existing `Success
Outcome` node now also carries the triggering alert's id. A new `Check
Alert Created` branch (reached only when `alertsCreated > 0`) calls
`POST /api/v1/cases` with the service token, using the **same acyclic,
unrolled retry pattern** Sprint 2 settled on after hitting a real n8n
Wait-node-loop bug -- 2 attempts here (not 3; case creation is lower
criticality than the financial transaction import itself) rather than a
custom loop.

The webhook's response now always includes `caseCreated`, `caseId`,
`caseStatus` (`"not_applicable"` when no alert was produced,
`"creation_failed"` if case creation itself exhausted its retries). This
is deliberately decoupled from the overall response status: a transaction
that imports successfully still returns `200` even if the downstream case
creation failed, since the transaction import is the primary contract --
case-creation failure is surfaced as data, not as an HTTP error, so
monitoring can catch it without the caller treating a successful ingest as
a failure.

Re-import/activation steps are identical to Sprint 2's (see
`docs/sprint-2-n8n-workflow-integration.md`) -- same `--projectId` gotcha
on re-import, same need to restart n8n after activating.

## A real bug found and fixed along the way

`InvestigationCase.updated_at` originally had `onupdate=func.now()`. That
makes SQLAlchemy mark the column "expired" after any UPDATE and defer
re-fetching it to the next attribute access -- which crashed with
`MissingGreenlet` when that next access was the synchronous Pydantic
response-building code running after `session.commit()` had already
returned (no async greenlet active to service the implicit reload).
Fixed by removing `onupdate` from the column and having
`assign_case`/`transition_status` set `case.updated_at =
datetime.now(timezone.utc)` explicitly in Python before flushing. No
migration change was needed -- `onupdate` is ORM-only behavior, not DDL.

## Known gaps (tracked, not fixed here)

- No `users`/`organization_memberships` table (plan.md §2 called for one).
  `assigned_analyst_id` and `actor_analyst_id` are bare UUIDs asserted by
  a JWT claim, not validated against a roster.
- The analyst JWT layer is a placeholder (see above) -- no real IdP, no
  rotation, no revocation. Tracked in
  `docs/pre-production-security-todo.md`.
- `case_evidence` is metadata only (title/description/a reference string)
  -- no file storage, hashing, or provenance. The full evidence service
  (readme.md Module 9 / plan.md Phase 3) is out of scope here.
- The database-role hardening backlog from Sprint 1
  (`docs/pre-production-security-todo.md`) remains open and untouched.

## Running the tests

```sh
cd services/api && pytest          # unit + integration, incl. tests/test_cases.py
cd tests/workflow && "../../services/api/.venv/Scripts/python.exe" -m pytest -q
```
