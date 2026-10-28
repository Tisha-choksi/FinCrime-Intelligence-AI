# Implementation Plan — Financial Crime Intelligence Platform

Derived from [readme.md](readme.md). This plan turns the 150-operation blueprint into a sequenced, actionable build plan starting from an empty repository.

Status: not started. No code exists yet — only the product blueprint in `readme.md`.

---

## 0. Guiding principles (carry through every phase)

- **Backend owns truth.** n8n orchestrates; it never holds business logic, risk rules, or authorization decisions directly in a node. Every workflow calls the FastAPI control plane.
- **Deterministic before AI.** Ship rule-based detection (`MON-*`, `RSK-*`) before AI agents (`AGT-*`). Agents assist, they don't decide.
- **Human-in-the-loop for consequential actions.** Anything that touches money, accounts, filings, or case closure goes through `approvals` + `proposed_actions`, never direct execution.
- **Tenant isolation from day one.** `organization_id` on every customer-owned row, enforced in backend authorization — not bolted on later.
- **Contract-first.** Every operation gets a stable ID, versioned input/output schema, and a test before it is wired into any workflow.
- **No operation is "done" on a JSON syntax check.** Release gate = contract + business logic + security + audit + failure recovery, all verified (see §7).

---

## 1. Repository bootstrap

Create the monorepo skeleton exactly as specified in readme.md §5:

```
financial-crime-intelligence/
├── apps/analyst-dashboard/
├── services/
│   ├── api/                  # FastAPI control plane
│   ├── ingestion/
│   ├── transaction-monitoring/
│   ├── risk-engine/
│   ├── entity-resolution/
│   ├── graph-analytics/
│   ├── case-management/
│   ├── ai-investigation/
│   ├── evidence-service/
│   ├── policy-engine/
│   ├── approval-service/
│   ├── action-executor/
│   └── connector-service/
├── n8n/{workflows/{core,monitoring,fraud,kyc,sanctions,network,cases,agents,evidence,risk,compliance,approvals,security,platform,tenant},subworkflows,manifests,schemas}/
├── contracts/{operations,events,api}/
├── database/{migrations,seeds,policies}/
├── datasets/{synthetic,evaluation}/
├── tests/{unit,integration,workflow,security,performance,evaluation}/
├── infra/{docker,monitoring}/
├── scripts/
├── docs/
├── docker-compose.yml
├── .env.example
├── Makefile
└── README.md
```

Tasks:
1. `git init`, initial commit with skeleton directories (empty dirs via `.gitkeep`).
2. Move current `readme.md` content into `docs/blueprint.md`; keep top-level `README.md` as the short project entry point that links to blueprint + this plan.
3. Fix the broken Mermaid diagrams (currently rendered CSS/JS pasted in instead of source) — rewrite the 4 diagrams as proper ` ```mermaid ` code blocks: architecture flow, workflow execution pattern, ER diagram, AI investigation engine flow.
4. Add `.env.example`, `Makefile` with `make up`, `make migrate`, `make test`, `make seed`.
5. Choose and pin versions: n8n version, Python version, Postgres version, Redis version, Node version for dashboard.

---

## 2. Platform core (Weeks 1–2 target)

Goal: a working skeleton where n8n can call an authenticated API, and every call is recorded.

1. **Docker Compose** — `postgres`, `redis`, `n8n`, `api` containers. Separate DB roles/users for app schema vs n8n's own schema. Bind admin ports to localhost only. Non-default secrets via `.env`.
2. **Database migrations (initial set)**:
   - `organizations`
   - `users`, `organization_memberships`
   - `operations`, `operation_versions` — the catalog registry
   - `operation_runs` — status, input/output refs, correlation_id, retries
   - `audit_events` — append-only, no update/delete grants for the app role
3. **Operation registry service** — CRUD-free, read-mostly API backed by `operations`/`operation_versions`; this is what `/operations` and `/operations/{id}` serve.
4. **API authentication** — OIDC-compatible bearer token validation middleware in FastAPI; a service-identity token for n8n → API calls; reject requests missing `organization_id` context.
5. **Audit event recording** — a single `record_audit_event()` helper used everywhere a material action happens; wire it into every endpoint from the start, not retrofitted later.
6. **First n8n integration** — one workflow that calls `GET /health/ready`, proving the credential, network, and auth path work end-to-end.
7. **Reusable subworkflows (`CORE-001`…`CORE-010`)** — build these before any domain workflow, per readme.md §4:
   - `CORE-001` validate input/schema
   - `CORE-002` create/update operation run
   - `CORE-003` idempotency check
   - `CORE-004` call authenticated backend service
   - `CORE-005` retry/timeout policy
   - `CORE-006` record audit event
   - `CORE-007` create human approval request
   - `CORE-008` revalidate approved action
   - `CORE-009` normalize errors / route failures
   - `CORE-010` publish metrics/execution events

Exit criteria: a dummy operation can be submitted via API, run through n8n using all 10 core subworkflows, and produce an audit trail — before any real detection logic exists.

---

## 3. Sprint 1 — Transaction ingestion to investigation alert (detailed, 5–7 days)

This is the first vertical slice and the immediate next step. Breaking the 10-item checklist from readme.md §14 into concrete sub-tasks:

| # | Task | Sub-steps |
|---|------|-----------|
| 1 | Monorepo + Compose foundation | §1 and §2.1 above |
| 2 | Separate app/n8n DB roles | Create `app_rw`, `app_audit_ro`, `n8n_internal` Postgres roles with least-privilege grants |
| 3 | Core migrations | `organizations`, `operations`, `operation_runs` tables + indexes on `organization_id`, `status`, `correlation_id` |
| 4 | Register `ING-001`, `ING-004` | Seed script inserts operation contracts (id, version, input schema, output schema, risk policy ref) into `operations`/`operation_versions` |
| 5 | CSV ingestion + validation + dedup | `services/ingestion`: `POST /operations/ING-001/runs` accepts file ref → schema validation (`ING-004`) → fingerprint hash of (org_id, source_id, amount, timestamp) for duplicate detection (`ING-006` logic pulled forward) |
| 6 | `MON-011` threshold rule | `services/transaction-monitoring`: deterministic, versioned config (e.g. `amount > threshold` per currency/org) — no ML, no LLM |
| 7 | n8n workflow calling FastAPI | `n8n/workflows/core/ingestion-to-alert.json` using `CORE-001..006` subworkflows |
| 8 | Persist alert + audit | `alerts` table insert + `audit_events` row with correlation_id linking ingestion run → monitoring run → alert |
| 9 | Tests | Malformed CSV, duplicate transaction replay, API-down mid-workflow (retry/idempotency), wrong-tenant file upload rejected |
| 10 | Docs | `docs/sprint-1-runbook.md`: startup (`make up`), running tests (`make test`), recovery (restart a failed run, replay a dead-lettered job) |

Milestone definition (from readme.md): a synthetic transaction file is ingested, validated, scored by a deterministic rule, and becomes a traceable alert via n8n — with no duplicate records and no unauthorized side effects.

---

## 4. Phase-by-phase roadmap (Weeks 3–16+)

Expanding readme.md §12 into what each phase actually delivers:

### Phase 2 — Financial data and monitoring (Weeks 3–4)
- Remaining Module 1 ops: `ING-002` (payment API webhook ingestion), `ING-003` (core banking sync), `ING-005` (normalization), `ING-007` (quality scoring), `ING-008` (quarantine), `ING-009` (reconciliation), `ING-010` (ingestion audit report).
- Remaining Module 2 ops: `MON-012`…`MON-020` (velocity, structuring, rapid movement, geographic, dormant reactivation, timing, concentration, round-amount, rule engine versioning).
- Rule versioning model: every `monitoring_rules` row has an immutable version; changing a threshold creates a new version, old alerts keep pointing at the version that generated them.

### Phase 3 — Cases and evidence (Weeks 5–6)
- Module 7 (`CAS-061`…`070`): alert→case creation, dedup, priority, assignment, checklist, SLA, evidence requests, status sync, escalation, closure validation.
- Module 9 (`EVD-081`…`090`): evidence registration, integrity hashing, provenance, evidence-to-claim linking, citation verification, gap reporting, report generation/validation, bundle export, version management.
- Module 6 basics (`NET-051`…`054`): entity resolution, account relationship mapping, shared identifiers, transaction chain reconstruction — using indexed Postgres recursive queries, not a graph DB yet (per readme.md §6).

### Phase 4 — AI investigation and approvals (Weeks 7–8)
- `services/ai-investigation`: agent scaffolding with defined scope, allowed tools, token/time budgets, structured output schema, and an eval suite per agent *before* it's wired into a workflow.
- Module 8 (`AGT-071`…`080`) in order: coordinator → transaction analysis → customer context → network analysis → policy research (RAG over policy docs, pgvector) → timeline reconstruction → contradiction detection → missing-evidence → report drafting → result verification (schema/citation/factual-support checks).
- `services/policy-engine` + `services/approval-service`: Module 12 (`APR-111`…`120`) — approval request, reviewer assignment, deadline monitoring, notification, payload verification, segregation-of-duties, decision recording, expiry, revocation, post-approval re-check.
- `services/action-executor`: the only component allowed to perform consequential side effects, gated by a valid, unexpired, re-validated approval.
- AI threat protection baked in here, not later: treat all retrieved/imported text as untrusted, test for prompt injection and fabricated citations as part of the agent eval suite.

### Phase 5 — Expand the catalog (Weeks 9–10)
- Module 4 (`KYC-031`…`040`), Module 5 (`SAN-041`…`050`), rest of Module 6 (`NET-055`…`060`), Module 10 (`RSK-091`…`100`), Module 11 (`CMP-101`…`110`), start of Module 14 (`PLT-131`…`140`).
- Decision point: evaluate whether Postgres relationship queries are hitting performance limits before introducing a graph database for Module 6's deeper traversals (`NET-055`, `NET-056`, `NET-058`).

### Phase 6 — Dashboard and packaging (Weeks 11–12)
- `apps/analyst-dashboard` (Next.js + TypeScript): case search, investigation view, evidence review, approval queue, audit explorer.
- Module 15 (`TEN-141`…`150`): org provisioning, policy config, user provisioning, connector onboarding, usage metering, entitlements, tenant reporting, health monitoring, support bundles, config backup.
- Module 13 (`SEC-121`…`130`): access audits, redaction, audit integrity verification, retention review, legal hold, secret expiry, suspicious access monitoring, tenant isolation testing, incident evidence packs.

### Phase 7 — Release readiness (Weeks 13–16+)
- Full test matrix from §7 run against the whole catalog, not just Sprint 1.
- Independent security review, backup/restore drill, performance test at target transaction/alert volume.
- Legal/compliance pass: n8n licensing for commercial use, model-provider terms, screening-data licenses, jurisdiction-specific claims review.
- Controlled pilot with a design partner on synthetic-then-governed data.

---

## 5. Cross-cutting workstreams (run in parallel, not sequential phases)

These don't belong to a single week — they need continuous attention starting in Phase 1:

- **Contracts (`contracts/operations/*.json`)**: one schema file per operation ID, versioned, reviewed before any workflow touches it.
- **Testing** (readme.md §11, 10 gates): unit → integration → workflow execution → idempotency/retry/recovery → tenant isolation/authz → approval tampering/expiry/replay → AI eval → performance → audit completeness → docs. Build the test harness in Phase 1 so later phases just add cases to it.
- **Security governance** (§10): tenant isolation + RBAC, secrets management with outbound allowlists, evidence/audit protection, AI threat protection, human accountability — these are design constraints applied to every phase, not a Phase 7 add-on.
- **Observability**: OpenTelemetry traces/structured logs/metrics wired in from the first API service, not retrofitted.

---

## 6. Explicit non-goals for the prototype

To keep scope honest against readme.md's own caveats:
- No real customer banking connections until Phase 7 pilot — synthetic data only through Phase 6.
- No graph database unless Phase 5's performance evaluation justifies it.
- No AI agent is granted direct write/execute access to money movement, account freezes, regulatory filings, or case closure — ever. Only `action-executor` behind an approval.
- No claim that AI-generated reports or risk scores constitute a compliance determination or proof of wrongdoing — this framing must appear in product docs, UI copy, and report templates, not just this plan.

---

## 7. Open decisions to make before/at Phase 1 kickoff

1. Self-hosted n8n vs n8n Cloud, and which license tier is valid for commercial resale (readme.md flags this explicitly — needs resolution before Phase 6 packaging, but cheaper to decide now).
2. Which OIDC provider to target first (Auth0/Keycloak/Entra) for the identity layer.
3. LLM provider(s) for `services/ai-investigation` — API-hosted vs self-hosted, and which model per agent role (cost/latency/eval tradeoffs).
4. Object storage choice for evidence files (S3-compatible: AWS S3, MinIO for local dev).
5. Initial target customer profile for the Phase 7 pilot, to make Phase 5 catalog prioritization concrete instead of doing all 15 modules at even depth.

---

## Immediate next action

Start **§1 Repository bootstrap** followed by **§3 Sprint 1**. Everything else in this plan is sequenced after that vertical slice proves the architecture end-to-end.
