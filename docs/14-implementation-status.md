# 14 — Implementation Status

> Snapshot as of the audit below. This doc tracks **what's actually built and
> verified** against the plan in [01](01-vision-scope.md)–[13](13-agent-build-plan.md),
> separate from the plan itself. Update it as the implementation moves — it will go
> stale fast otherwise, so trust `git log` and the test suite over this doc's prose
> if they disagree.

## How this was verified

Every claim below was checked by running the actual test suite
(`pytest tests/ -q` → 31 passed, 11 skipped) and reading the implementation
against the port contracts in [03](03-tech-stack.md) and the agent build order in
[13](13-agent-build-plan.md). This is a fast-moving codebase — another contributor
has been actively building it in parallel throughout this doc's history, so treat
this snapshot as a point-in-time reference, not a permanent inventory.

## Finished

### Domain & ports (matches [03](03-tech-stack.md))
- All 10 ports from the plan are defined as real `Protocol` types in
  `packages/core/src/aegis_dx/ports.py`: `IngestionPort`, `TriagePort`,
  `SpecialistPort`, `RetrievalPort`, `SynthesisPort`, `ReportPort`,
  `VerificationPort`, `GuardrailPort`, `AuditPort`, `IdentityPort` — plus a newer
  `CaseStorePort` structural protocol so `WorkflowRuntime` accepts SQLite or
  Postgres interchangeably.
- The `CaseRecord` state shape matches [02](02-architecture.md)'s state design:
  `case_id`, `trace_id`, `tenant_id`, `site_id`, `status`, `findings[]` (with
  `locus`, `probability`, `source_agent`, `model_version`, `saliency_ref`),
  `verification[]`, `differential[]`, `escalation`, `report`, `human_review`.

### Case lifecycle state machine (matches [08](08-scalability-architecture.md))
- The full state machine is implemented in `workflow.py`:
  `Received → DeIdentified → Triaged → Analyzing → Verifying → Synthesized →
  Calibrated → (Escalated | Degraded) → AwaitingReview → (Confirmed | Edited | Rejected)`.
- Idempotent intake via `Idempotency-Key` header, per [11](11-engineering-practices.md).
- Correlation-ID propagation (`X-Correlation-Id` header + `contextvars`-based
  binding) through every workflow step, matching [10](10-observability-mlops.md)'s
  "case ID = trace ID" principle.

### Agents implemented as adapters (per [13 — Agent Build Plan](13-agent-build-plan.md))
| Agent | Adapter | Notes |
|-------|---------|-------|
| Ingestion | `StubIngestionAdapter` | De-identifies MRN-shaped IDs and emails via regex. Real but intentionally minimal. |
| Triage | `StubTriageAdapter` | Modality/region/urgency from MIME type + keyword rules. |
| **CXR specialist** | `ModelBackedChestXRaySpecialistAdapter` (default) or `HFTorchXRayVisionSpecialistAdapter` | HTTP-backed (default): calls a configurable endpoint (e.g. a hosted MedGemma deployment), falls back to the keyword-based stub on any failure. **Or** locally-run: `HFTorchXRayVisionSpecialistAdapter` (`AEGIS_DX_CXR_SPECIALIST_BACKEND=torchxrayvision-local`) runs torchxrayvision's real, independently-trained CheXpert DenseNet121 in-process against an image resolved from `artifact.artifact_uri` — no external endpoint at all. Both fall back to the same keyword-based stub under failure. |
| **ECG specialist** | `ModelBackedECGSpecialistAdapter` | Sends de-identified ECG artifact context to a configurable PTB-XL model endpoint (`AEGIS_DX_ECG_SPECIALIST_ENDPOINT_URL`) and maps trained multi-label findings into the shared `Finding` contract. Falls back to a transparent signal-review stub when the endpoint is not configured or unavailable. |
| Retrieval / RAG | `StubRetrievalAdapter` | A small in-code guideline corpus, retrieved by modality/region match. |
| Synthesis | `StubSynthesisAdapter` | Fuses findings + evidence into a ranked differential. |
| **Verifier/critic** | `ModelBackedVerificationAdapter` or `HFTorchXRayVisionVerificationAdapter` | Calls an independent, configurable critic endpoint by default, or a locally-run torchxrayvision checkpoint with `AEGIS_DX_VERIFIER_BACKEND=torchxrayvision-local`. Both fall back to the rule-based verifier under failure. `assert_heterogeneous_verifier()` refuses identical endpoint URLs and also prevents using the same local torchxrayvision model for both specialist and verifier. |
| Guardrail | `StubGuardrailAdapter` | Escalates on STAT urgency, missing evidence, or accumulated verifier flags. |
| Reporter | `StubReportAdapter` | Composes a structured summary + rendered findings + evidence links + the research-only disclaimer, including verifier agreement, critic flags, and the final guardrail escalation decision. |
| Orchestrator | `WorkflowRuntime` | The graph-equivalent — not LangGraph yet (see Gaps), but the sequencing and the `Degraded` resilience path are real and tested. |

### Production infrastructure (new this round)
- **Postgres**: `PostgresCaseStore` mirrors `SQLiteCaseStore`'s exact method
  surface and hash-chained audit-log logic on real Postgres tables (`psycopg2`).
  Selected automatically when `AEGIS_DX_DATABASE_URL` is set; SQLite remains the
  dev/test default. `docker-compose.yml` provides a local Postgres for
  development.
- **Durable queue**: `CaseQueuePort` abstracts the workflow's dispatch queue.
  `InProcessCaseQueue` (the prior `queue.Queue`, still the default) and
  `RedisStreamCaseQueue` (Redis Streams + consumer group, XACK-on-completion for
  at-least-once delivery) are both real implementations. Selected via
  `AEGIS_DX_REDIS_URL`.
- **Standalone worker**: `apps/worker/main.py` runs the same `WorkflowRuntime`
  processing loop as its own process (`python -m apps.worker.main`) — with Redis
  + Postgres configured, intake (the API) and processing (this worker) no longer
  need to share a process, closing the biggest gap from [08](08-scalability-architecture.md).
- **CI pipeline**: `.github/workflows/backend-ci.yml` runs ruff, mypy, and the
  full pytest suite (including real Postgres + Redis service containers) on
  every push/PR — the Definition of Done in [11](11-engineering-practices.md)
  is now actually enforced, not just documented.
- **Locally-run HF model wrappers** (`packages/core/src/aegis_dx/models/`) —
  distinct from the HTTP adapters above, these actually download and run a real
  checkpoint in-process, verified against the genuine weights (not mocked):
  - `TorchXRayVisionClassifier` — wraps torchxrayvision's real
    `densenet121-res224-chex`, wired into the workflow via
    `HFTorchXRayVisionSpecialistAdapter` (see the CXR specialist row above).
  - `MedSAMRefiner` — wraps `flaviagiammarino/medsam-vit-base`
    (a `transformers`-native SAM port) for box-prompted interactive
    segmentation. It is available through `POST /v1/segmentations/refine` and
    the clinician dashboard's case-detail refinement panel; it accepts a
    readable local image URI and an in-bounds box, then returns an RLE mask
    summary for research-only clinician review. `MedGemma` and `CT-FM` remain HTTP-only for now: MedGemma is
    gated + ~8GB+ (impractical to download/run in this environment), and CT-FM
    depends on the `project-lighter` custom framework, not yet integrated.

### Bounded agentic loops (per [15 — Agentic Architecture](15-agentic-architecture.md))
- **Consensus module** (`consensus.py`) — real Cohen's κ between the specialist's
  and verifier's implied binary calls per case (`compute_case_consensus`), a
  `requires_requery` predicate, and `classify_complexity_tier` (Tier 1/2/3),
  all pure/deterministic and unit-tested independently of the workflow.
- **Verify↔re-query loop** (`WorkflowRuntime`, docs/15 §5.2) — on disagreement
  (a verifier disagreement flag or low κ), the workflow loops `VERIFYING` back
  to `ANALYZING` to re-run specialist analysis + verification, bounded to
  `MAX_VERIFICATION_ROUNDS = 2`. Bound-exhaustion never hides the disagreement —
  it emits `workflow.verification_loop_exhausted` and the guardrail's existing
  disagreement-escalation logic surfaces it to the clinician. Every round is
  audit-traced (`workflow.reverified`) and the final complexity tier is recorded
  (`workflow.complexity_routed`). Verified with a real (not mocked) integration
  test using disagree-then-agree and always-disagree verifier doubles that prove
  the loop actually iterates, converges, and terminates at the bound.
- **Reflexion loop** (`ReflexiveSynthesisAdapter`, docs/15 §5.1) — wraps
  `StubSynthesisAdapter` in the default composition: a self-evaluator checks
  every differential item cites a specific finding's locus/source and isn't
  overconfident relative to the strongest supporting finding; below threshold,
  a bounded repair-and-retry (`max_revisions = 2`) runs before giving up and
  flagging `reflexion_incomplete`. Passes the same shared `SynthesisPort`
  contract test as any other synthesis adapter (D14's contract-test discipline).
  Deterministic today (no new model training, per this round's scope) but
  implements the same evaluate→revise interface a real LLM-backed critique step
  would use — swapping one in later is additive, not a redesign.
- **Not yet implemented:** the Tier-3 consultation/debate loop (docs/15 §5.3) —
  it needs a genuine multi-specialist panel to be meaningful; tracked in the
  Known Gaps table below.

### Security & audit walking skeleton (per [09](09-security-identity-audit.md))
- Header-based principal resolution (`X-Actor-Id` / `X-Actor-Role` / `X-Tenant-Id`)
  directly in `api/app.py`, gating each endpoint via `require_roles(...)`.
- Tenant scoping enforced in `WorkflowRuntime.get_case` — a clinician cannot fetch
  another tenant's case (`PermissionError` on mismatch).
- **Append-only, hash-chained audit log** — chains each entry's SHA-256 hash to
  the previous entry's hash, per case+tenant, in both `SQLiteCaseStore` and
  `PostgresCaseStore`, exactly as specified in [09](09-security-identity-audit.md).
- Case-lifecycle event log (separate from the audit log) with a **versioned event
  schema registry**, exposed at `/v1/event-schemas` and `/v1/cases/{id}/events` —
  matches [11](11-engineering-practices.md)'s API conventions section.

### API surface
`POST /v1/cases` (202 + idempotency), `GET /v1/cases`, `GET /v1/cases/{id}`,
`GET /v1/cases/{id}/audit`, `GET /v1/cases/{id}/events`, `GET /v1/event-schemas`,
`POST /v1/cases/{id}/review`, `POST /v1/segmentations/refine`,
`GET /v1/model-status`, `GET /healthz`, `GET /metrics`. Role-gated per endpoint
except the health and Prometheus-compatible metrics endpoints. The model-status
response reports backend, version, execution mode, and fallback posture without
exposing URLs or credentials. It also reports whether local optional dependencies
are present or a remote endpoint is configured; it does not perform a network
health call. Metrics contain only bounded operational labels.

### Test coverage
- **8 of 10 ports have a shared contract test suite** in `tests/contracts/`:
  ingestion, triage, specialist, retrieval, synthesis, report, verification,
  guardrail — wired up in `test_port_contracts.py`. (`AuditPort` and
  `IdentityPort` don't have a generic contract suite yet — only one adapter
  exists for each today.)
- `test_api.py` exercises the full state machine end-to-end: submission, triage,
  analysis, verification, synthesis, calibration, the degraded path, idempotent
  replay, tenant isolation, the audit/event trails, **and** the model-backed
  specialist/verifier (configured, failure-fallback, and the heterogeneous-verifier
  startup guard).
- `test_model_backed_adapters.py` — 11 unit tests covering both new adapters in
  isolation (well-formed response, transport failure, malformed response, empty
  findings, no-op on empty input).
- `test_postgres_store.py` / `test_redis_queue.py` — real (not mocked) integration
  tests against actual Postgres/Redis, skip gracefully without local infra, run
  for real in CI.
- `test_torchxrayvision_specialist.py` / `test_medsam_backend.py` — same pattern,
  but for the locally-run HF wrappers: fast unit tests with a fake classifier,
  plus one real end-to-end test per model that actually downloads the weights
  and runs live inference (skips gracefully if the `imaging` extra isn't
  installed).
- `test_consensus.py` / `test_reflexion.py` / `test_verification_loop.py` — the
  bounded agentic loops: κ math against hand-computed expectations, the
  reflexion evaluator/repair cycle (including a genuinely unfixable-input case
  that proves the bound gets hit rather than looping forever), and a real
  `WorkflowRuntime` integration test using disagree-then-agree / always-disagree
  verifier doubles that proves the verify↔re-query loop actually iterates,
  converges, and terminates.
- Backend tests passing, several skipping cleanly (Postgres/Redis/imaging
  extras depending on what's installed locally) — see the latest CI run for the
  authoritative count, this doc's own count goes stale fast. ruff and mypy both
  clean as of this audit.

### Clinician dashboard ([apps/web](../apps/web))
React + TypeScript + Vite app, rebuilt from scratch this round after the prior
source was found missing from disk (never committed, no recoverable copy —
see git history for `apps/web` if the full story matters). Matched by hand
against the current backend API and domain models (`src/lib/types.ts` mirrors
`domain.py`). Case list, case detail (overview, findings + verifier agreement,
differential, evidence with links, case lifecycle timeline, audit trail),
a case-submission form (including an optional local artifact URI for trained
model execution), a model-posture panel, a MedSAM box-refinement panel with
RLE mask metadata, and the confirm/edit/reject review form gated on
`status === AwaitingReview`. The Vite dev server proxies `/v1` and `/healthz`
to the backend so there's no CORS dependency in dev.

**Verified two ways**, not just unit-tested: 6 component tests (mocked fetch)
covering the detail view, review-locking, confirm submission, the
edit-requires-summary rule, the role-specific 403 message on the audit log, and
case submission — all green, clean `tsc -b`. Then a live end-to-end pass in an
actual browser against a running backend: submitted a case through the UI,
watched it process asynchronously through triage → analysis → verification →
synthesis → calibration, reviewed and confirmed it, and inspected the real
hash-chained audit trail under the reviewer role. No console errors.

## Fixed in an earlier audit pass (still holds)

**Degraded cases never reached the clinician with a report.** Fixed by building
a `StructuredReport` directly in both `Degraded`-triggering branches in
`workflow.py` before transitioning, so `case.report` is always populated. Locked
in with test assertions. See git history (`git log --oneline -- workflow.py`) for
the exact commit if you need the full narrative.

## Known gaps (intentional simplifications — "thin slice," not bugs)

Consistent with the "thicken later, don't retrofit" principle in
[08](08-scalability-architecture.md) and [05](05-roadmap.md).

| Gap | Plan says | Currently | Tracked as |
|-----|-----------|-----------|------------|
| Orchestration engine | LangGraph ([D5](07-risks-decisions.md)) | Hand-written `while` loop over `CaseStatus` in `WorkflowRuntime._process_case`, now dispatching through `CaseQueuePort` | Same state machine shape; migrate the *engine*, not the *design* |
| Crash-durability of in-flight state | Durable checkpointing ([08](08-scalability-architecture.md)) | The queue (Redis) and store (Postgres) are now durable, but there's no mid-case checkpoint — a worker crash mid-`_process_case` re-runs from the last saved `CaseStatus`, not a finer-grained resume point | Acceptable for now (idempotent-ish per state transition); revisit if a step becomes expensive to re-run |
| Identity | OIDC/SAML SSO ([09](09-security-identity-audit.md)) | Header-based principal read inline in `api/app.py` | Swap behind `IdentityPort` when real SSO lands — the port already exists |
| Real endpoints configured | MedGemma 1.5 + a real critic model both live ([04](04-data-models.md), [D6](07-risks-decisions.md)) | The adapters are real and tested; no live `AEGIS_DX_CXR_SPECIALIST_ENDPOINT_URL` / `AEGIS_DX_VERIFIER_ENDPOINT_URL` is actually pointed at a running model yet | Point the env vars at a real deployment — no code change needed |
| `ReportPort.compose` signature | Report reflects verification + escalation state | Internal port now receives verification results and the final escalation decision; public `CaseRecord` shape is unchanged | Adapter-backed trust/report context is live |
| Observability | OpenTelemetry → Tempo/Jaeger, Prometheus/Grafana ([10](10-observability-mlops.md)) | Correlation IDs propagate, the workflow records bounded counters, and `/metrics` exposes Prometheus text; OTel export, dashboards, and alerting are not wired | Continue with deployment-level collector/dashboard configuration |
| MLOps | Model registry, eval gates, shadow/canary ([10](10-observability-mlops.md)) | Local pretrained model inference and a credential-safe runtime posture endpoint are wired, but there are no project-owned training artifacts, evaluation gates, or deployment promotion controls | Starts with [12 — Training Plan](12-training-plan.md) Vertical 1 |
| Retrieval corpus | Vector DB (Qdrant/pgvector) over a real guideline corpus ([03](03-tech-stack.md)) | A few hand-written documents scored in-process | Real corpus + vector DB when RAG needs to scale past demo cases |
| Additional verticals | 8 modalities ([01](01-vision-scope.md)) | 2 (`chest_xray`, `ecg`); both are registered through `SpecialistRegistry` and traverse the same workflow. ECG uses a configurable PTB-XL endpoint with a safe fallback until a deployment is configured | Continue per [05 — Roadmap](05-roadmap.md) Phase 6+ |
| Tier-3 consultation/debate loop | MetaAgent + specialist panel + devil's-advocate, κ-consensus exit ([15](15-agentic-architecture.md) §5.3) | Not built — `classify_complexity_tier` already labels cases `tier_3_panel`, but nothing consumes that label to actually convene a panel yet | Needs a second specialist genuinely in the loop; natural to build alongside vertical #2 |
| LLM-backed reflexion/verification | A real self-critique/critic model reasoning over text, not rule-based checks ([15](15-agentic-architecture.md) §5.1) | `ReflexiveSynthesisAdapter`'s evaluator/reviser and the verify-loop's disagreement detection are deterministic (grounding/threshold checks) | Same interface either way — point an LLM-backed `SynthesisPort`/`VerificationPort` at the loop, no loop-mechanism changes needed |

## What's genuinely next (not yet started, not a stand-in)

- **Additional trained vertical deployments** — the ECG adapter and workflow route
  are live, but the PTB-XL checkpoint still needs to be deployed behind
  `AEGIS_DX_ECG_SPECIALIST_ENDPOINT_URL` before trained ECG inference replaces the
  transparent fallback.
- **Point the model endpoints at something real** — the specialist and verifier
  adapters are production-shaped; they just don't have a live model behind them
  yet. This is now a config/deployment task, not a code task.
- **Local verification of Postgres/Redis was not possible in this environment**
  (Docker Desktop's engine wasn't running, no reachable local Postgres) — CI is
  the first real end-to-end run against both. Check the Actions tab before
  trusting the Postgres/Redis paths in a new environment.
- **This codebase has been actively developed by more than one contributor.**
  Before trusting this doc, re-run `pytest tests/ -q` and diff the port files
  against what's described here — it may already be stale.
