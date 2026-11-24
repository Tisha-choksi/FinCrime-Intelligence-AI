# Sprint 4 — Identity, authorization, and audit infrastructure

Replaces Sprint 3's placeholder HS256 analyst JWT with a real OIDC
provider (Keycloak), a real user/membership data model, validated
assignee checks, authorization-failure auditing, evidence integrity
hashing + access logging, and a database role split separating
migrations from runtime queries. No database roles were changed
*silently* -- every change below was tested on a disposable Postgres
container first (same discipline as Sprint 1), then reviewed before
being applied to the live, non-recreated Postgres container. **Neither
the Postgres nor Redis container was recreated this sprint** -- the
Postgres container is the same one running since Sprint 1 (checked via
`docker ps` before and after every change); only the `api` and new
`keycloak` containers were built/recreated, which the task's own rules
permit.

## Why Keycloak, and what "real OIDC" means here

n8n, the n8n Postgres schema, and the n8n Postgres volume were never
touched. Keycloak (`quay.io/keycloak/keycloak:26.0.7`) runs as a new
container, using a new Postgres role/schema (`keycloak_internal`/`keycloak`)
on the *same* already-running Postgres container -- created the same way
`n8n_internal`/`n8n` and `app_runtime`/`app` were: manually, via `psql`
against the live container, never by recreating it.

The API validates tokens for real:
- **Signature**: RS256 via Keycloak's JWKS endpoint (`jwt.PyJWKClient`,
  cached). A token signed by any other key -- including a structurally
  perfect forgery -- is rejected because its key can't be resolved from
  Keycloak's trusted key set.
- **Issuer**: must exactly equal `OIDC_ISSUER_URL`, which is itself fixed
  via `KC_HOSTNAME=http://keycloak:8080` in Keycloak's own config, not
  derived from whatever host:port a caller used to reach it (a real
  footgun otherwise -- see "A real bug" below).
- **Audience**: must include `fincrime-api`, added to every token via an
  `oidc-audience-mapper` protocol mapper in `infra/keycloak/realm-export.json`.
- **Expiry**: enforced by `jwt.decode`, verified with a *real* token from
  a short-lived test client (`fincrime-cli-shortlived`, 2-second access
  tokens) -- the test actually waits for it to expire, not a mocked clock.

**What's still a placeholder, honestly:** the n8n service token
(`N8N_API_SERVICE_TOKEN`) is unchanged -- a static shared secret, not an
OIDC client. It can only ever call `POST /api/v1/cases` (case creation on
a qualifying alert); every other case endpoint explicitly rejects it.
Replacing it with a real service-account OIDC client is tracked, not done.

## Identity model: Keycloak owns identity, we own tenancy

This is the main architectural decision this sprint made, and it's worth
stating plainly: **Keycloak tokens carry no organization or role claim at
all.** They carry `sub`, `email`, `preferred_username` -- pure identity.
Which organization(s) a user belongs to, and with what role, lives
entirely in two new tables:

- `app.users` -- one row per verified subject, JIT-provisioned/updated on
  every authenticated request (`app/core/security.py::_sync_user`). Never
  created through a signup flow; it's a local shadow of whatever Keycloak
  already verified.
- `app.organization_memberships` -- `(user_id, organization_id, role)`,
  unique per pair. The sole source of truth for tenant scoping.

A caller asserts which org they're acting in via the `X-Organization-Id`
header. The server looks up a real membership row before trusting that
assertion -- an identity with no membership for the asserted org is
rejected with `403`, regardless of how valid their token is. This is a
deliberate upgrade from Sprint 3, where the organization was an
unvalidated claim baked into the token itself; now it's checked against
real rows on every request, and a user can belong to multiple
organizations with different roles in each (the IdP doesn't need to know
that).

**CAS-062 now validates the target analyst too**: `assign_case` queries
`organization_memberships` for `(target_analyst_id, case.organization_id)`
before accepting an assignment -- `InvalidAssigneeError` (400) if no such
row exists. This replaces Sprint 3's documented gap ("no user directory
exists yet, so this is identity-claim-based, not validated against a real
roster").

## Authorization-failure auditing

Every denial writes an `authorization.denied` audit_events row *before*
raising the HTTP exception, covering both layers:
- **Identity/org-level** (`app/core/security.py::_deny`): missing/invalid/
  expired/forged token, missing `X-Organization-Id`, or no membership for
  the asserted org. `entity_type="auth"` (no case context exists yet at
  this point).
- **Business-rule level** (`app/services/cases.py::_audit_denied`): a
  plain analyst trying to assign/reassign beyond their rights, or an
  invalid assignee. `entity_type="case"`, tied to the specific case, so it
  shows up in that case's own CAS-065 history.

(A first version of `_audit_denied` used `entity_type="auth"` here too --
caught by `test_authorization_failure_is_audited` failing, since
`get_case_history`'s query filters on `entity_type='case'`. Fixed by
tying business-rule denials to the case they occurred on.)

## Evidence: integrity hash + access logging

`case_evidence` gained `content` (an inline text excerpt, not a file) and
`content_hash` (SHA-256 over it). `POST .../evidence` computes and stores
the hash; the new `GET .../evidence` endpoint recomputes it on every read
and reports `integrity_ok` per item -- a row whose `content` was altered
directly in the database (bypassing the API entirely) is detected, not
silently trusted. Every `GET` is itself an audited `case.evidence_accessed`
event (item count + accessing user), satisfying both the audit and
access-logging asks together.

This is **not** the full evidence service (readme.md Module 9 / plan.md
Phase 3's object-storage decision, still open) -- no file upload, no
provenance chain, no external storage. It's a lightweight, honestly-scoped
tamper-detection mechanism for a small text excerpt, verified to actually
catch tampering (see test below) rather than asserted to.

## Database role split (docs/pre-production-security-todo.md items 2 & 3)

Validated on a disposable Postgres container first (create `app_migrator`,
transfer `app`'s schema + all table ownership to it, grant `app_runtime`
DML via `ALTER DEFAULT PRIVILEGES` so *future* tables are usable
immediately, create read-only `app_audit_ro`) -- confirmed the exact
privilege matrix (app_runtime: DML yes, DDL no; app_migrator: DDL yes;
app_audit_ro: SELECT on audit_events/case_history only, nothing else, no
writes anywhere) -- then applied the identical statements to the live
database via direct `psql`, never via container recreation.

- **`app_migrator`**: new, non-superuser, owns schema `app`. Alembic now
  connects as this role (`migrations/env.py` reads
  `POSTGRES_APP_MIGRATOR_USER/PASSWORD` directly from the environment,
  never from the app's own `Settings` -- the running API process must
  never hold a DDL-capable credential in memory).
  - A real migration (`b794c1007fea_grant_app_audit_ro...py`) grants
    `app_audit_ro` SELECT on `audit_events`/`case_history` as raw SQL
    (`op.execute(...)`), since those tables don't exist yet at
    first-init time on a fresh volume -- reviewed before applying.
- **`app_runtime`**: unchanged credential, but **no longer owns anything**
  -- now DML-only (`SELECT, INSERT, UPDATE, DELETE` + sequence usage via
  default privileges), confirmed denied on `CREATE TABLE`.
- **`app_audit_ro`**: new, read-only, confirmed it can read
  `audit_events`/`case_history` and is denied on every other table
  (including `organizations`) and on every write, including to
  `audit_events` itself.

**A real regression this caused, and the fix**: `TRUNCATE` requires table
*ownership* in Postgres, not just `DELETE` privilege -- so the test
suite's `clean_db` fixture (which ran as `app_runtime`) broke the moment
ownership moved to `app_migrator`. Rather than widening `app_runtime`'s
production privileges just for test convenience (which would partly undo
the point of this split), `clean_db` now issues per-table `DELETE`
statements instead, which `app_runtime`'s existing DML grant already
covers.

## A real bug found and fixed: issuer string vs. JWKS fetch address

`oidc_jwks_url` was originally *derived* from `oidc_issuer_url`
(`f"{issuer}/protocol/openid-connect/certs"`). That's correct for the
real deployed system, where the API always runs inside the Docker
network and both URLs are `http://keycloak:8080/...`. It breaks for
`pytest` running the FastAPI app in-process via `ASGITransport`: a real
Keycloak-issued token's `iss` claim must still say `http://keycloak:8080/...`
(that's genuinely what Keycloak embeds, fixed via `KC_HOSTNAME`,
regardless of caller), but the test process runs on the *host* and can't
resolve the hostname `keycloak` to fetch the JWKS over HTTP -- got
`getaddrinfo failed`. Fixed by splitting them into two independent
settings (`oidc_issuer_url` for the claim-equality check,
`oidc_jwks_url_override` -- env var `OIDC_JWKS_URL` -- for the actual
network address), with `tests/conftest.py` overriding only the latter to
the host-mapped Keycloak port. This also surfaced that
`test_incorrectly_signed_token_rejected` had been passing for the wrong
reason (the DNS failure also produced a 401, masking the real check) --
tightened its assertion once the real path worked.

Also hit and fixed along the way: Keycloak 26's new "Hostname v2" provider
rejects the old `KC_HOSTNAME_PORT` option (must pass the full URL,
`KC_HOSTNAME=http://keycloak:8080`, not host+port separately); a brand
new Keycloak realm's `VERIFY_PROFILE` required action fires dynamically
on users missing `firstName`/`lastName`, independent of its
`defaultAction` flag, breaking the direct-grant token flow until disabled
in `infra/keycloak/realm-export.json`; PyJWT's RS256 support needs the
`cryptography` package, never added in Sprint 3 (HS256-only) --
`services/api/requirements.txt` now includes it; and a fixture bug where
`session.add(User(...))` followed immediately by
`session.add(OrganizationMembership(...))` in the same flush does **not**
guarantee insert order across two mapped classes with no ORM
`relationship()` linking them, intermittently violating the FK -- fixed
with an explicit `await session.flush()` between the two.

## Testing requirements: what's covered and how

All of these are real integration tests against a real local Keycloak
(`tests/conftest.py::analyst_client_factory` creates a genuine, disposable
Keycloak user per call via the Admin API, mints a real access token via
the password grant, and deletes the user afterward) and the live
`app_runtime`-connected Postgres -- not mocked.

| Requirement | Test(s) |
| --- | --- |
| Cross-organization access denial | `test_analyst_cannot_read_case_from_other_org`, `..._assign_case_from_other_org`, `..._change_status_of_case_from_other_org`, `test_analyst_with_no_membership_anywhere_is_denied` |
| Invalid / expired / incorrectly signed tokens | `test_garbage_token_rejected`, `test_expired_token_rejected` (real 2-second-lifespan token, real wall-clock wait), `test_incorrectly_signed_token_rejected` (real forged RSA signature) |
| Role and permission enforcement | `test_analyst_can_self_claim_unassigned_case`, `test_plain_analyst_cannot_assign_unassigned_case_to_someone_else`, `test_plain_analyst_cannot_reassign_another_analysts_case`, `test_lead_can_reassign_any_case`, `test_service_token_cannot_assign_cases` |
| Invalid analyst assignment | `test_invalid_analyst_assignment_rejected` |
| Audit event creation and tamper-resistance | `test_authorization_failure_is_audited`, `test_case_history_and_audit_events_include_correlation_ids`, `test_evidence_tampering_is_detected_on_read` |
| Evidence access authorization | `test_evidence_access_is_audited_and_integrity_verified` |
| Migration isolation (app schema only) | `migrations/env.py`'s `include_name` filter (unchanged from Sprint 1, re-verified this sprint); live verification: `app` has 12 tables after this sprint's migrations, `n8n` still has exactly 32, untouched |
| Existing Sprint 1-3 regression | Full `services/api` suite: **45 passed** (12 pre-existing + 33 Sprint 4); `tests/workflow`: Sprint 2/3's suite re-run against the live stack after rebuilding `api` |
| Clean-state deployment verification | See "Honest limits" below -- partial, not full |

### Honest limits on "clean-state" verification

What was actually verified: the live Postgres container was never
recreated, and every role/ownership/grant change was validated end-to-end
against it afterward (health checks, DML/DDL privilege probes, a full
n8n-workflow-triggered case creation). Keycloak's container was rebuilt
multiple times during debugging (hostname config fixes) against its
*existing* `keycloak` schema/role, each time coming back up clean.

What was **not** independently re-verified this sprint: a genuinely fresh
Postgres volume running `02`/`05`/`06`'s init scripts and the full
Alembic migration chain from zero, with Keycloak also importing its realm
into a fresh `keycloak` schema from zero, all at once. Sprint 1 did this
kind of from-scratch verification for the original role split; Sprint 4's
role/identity changes build on that same mechanism but the *combined*
fresh-volume path (Postgres + Keycloak + all four role-creation scripts +
all five migrations) was not run end-to-end from an empty volume this
sprint. Treat the init scripts as reviewed and individually consistent
with the live-verified live state, not as independently proven from
zero.

## Known gaps (tracked, not fixed here)

- No real service-account OIDC client for n8n -- still the Sprint 1
  static shared token, now explicitly scoped to case-creation only.
- No key rotation, refresh-token handling, or session/logout UI -- access
  tokens are short-lived (5 minutes) and that's the only mitigation in
  place for now. Token introspection (for instant revocation ahead of
  expiry) was not implemented.
- `app_rw` is still a Postgres superuser, used only for bootstrap/init
  scripts -- unchanged from Sprint 1's open item.
- No real RBAC system -- "lead" vs "analyst" is still two string values
  compared in application code, now backed by a real roster
  (`organization_memberships`) but not a general permissions framework.
- Evidence integrity hashing covers a small inline text excerpt only, not
  files. The full evidence/object-storage service remains out of scope.

**This sprint's work makes local identity/authorization genuinely more
real and independently verified than Sprint 3's placeholder -- it does
not make the system production-ready.** No code review, penetration
test, or external security audit has occurred. Treat every claim above
as "verified locally, this session" and nothing more.

## Running the tests

```sh
docker ps --filter name=fincrimeintelligenceai   # confirm postgres/redis/n8n/keycloak/api all up
cd services/api && pytest                         # 45 tests, ~4 min (real Keycloak round-trips)
cd tests/workflow && "../../services/api/.venv/Scripts/python.exe" -m pytest -q
```
