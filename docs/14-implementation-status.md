# 14 — Implementation Status

> Snapshot as of the audit below. This doc tracks **what's actually built and
> verified** against the plan in [01](01-vision-scope.md)–[13](13-agent-build-plan.md),
> separate from the plan itself. Update it as the implementation moves — it will go
> stale fast otherwise, so trust `git log` and the test suite over this doc's prose
> if they disagree.

## How this was verified

Every claim below was checked by running the actual test suite
(`pytest tests/ -q` → 16 passed) and reading the implementation against the port
contracts in [03](03-tech-stack.md) and the agent build order in
[13](13-agent-build-plan.md). This is a fast-moving codebase — another contributor
is actively building it in parallel, so treat this snapshot as a point-in-time
reference, not a permanent inventory.

## Finished

### Domain & ports (matches [03](03-tech-stack.md))
- All ports from the plan are defined as real `Protocol` types in
  `packages/core/src/aegis_dx/ports.py`: `IngestionPort`, `TriagePort`,
  `SpecialistPort`, `RetrievalPort`, `SynthesisPort`, `ReportPort`,
  `VerificationPort`, `GuardrailPort`, `AuditPort`, `IdentityPort`.
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
| CXR specialist | `StubChestXRaySpecialistAdapter` | Keyword-based findings (pneumonia/effusion/normal), correctly shaped `Finding` objects with locus + saliency_ref. Not model-backed yet. |
| Retrieval / RAG | `StubRetrievalAdapter` | A small in-code guideline corpus, retrieved by modality/region match. |
| Synthesis | `StubSynthesisAdapter` | Fuses findings + evidence into a ranked differential. |
| Verifier/critic | `StubVerificationAdapter` | Rule-based — flags low confidence, missing evidence, tentative language; computes an independent `agreement_score`. Not yet a second model ([D6](07-risks-decisions.md)) — heterogeneous by construction (not an LLM at all yet) rather than by design. |
| Guardrail | `StubGuardrailAdapter` | Escalates on STAT urgency, missing evidence, or accumulated verifier flags. |
| Reporter | `StubReportAdapter` | Composes a structured summary + rendered findings + evidence links + the research-only disclaimer (hardcoded default). |
| Orchestrator | `WorkflowRuntime` | The graph-equivalent — not LangGraph yet (see Gaps), but the sequencing and the `Degraded` resilience path are real and tested. |

### Security & audit walking skeleton (per [09](09-security-identity-audit.md))
- Header-based principal resolution (`X-Actor-Id` / `X-Actor-Role` / `X-Tenant-Id`)
  directly in `api/app.py`, gating each endpoint via `require_roles(...)`.
- Tenant scoping enforced in `WorkflowRuntime.get_case` — a clinician cannot fetch
  another tenant's case (`PermissionError` on mismatch).
- **Append-only, hash-chained audit log** — `SQLiteCaseStore.append_audit_event`
  chains each entry's SHA-256 hash to the previous entry's hash, per case+tenant,
  exactly as specified in [09](09-security-identity-audit.md).
- Case-lifecycle event log (separate from the audit log) with a **versioned event
  schema registry**, exposed at `/v1/event-schemas` and `/v1/cases/{id}/events` —
  matches [11](11-engineering-practices.md)'s API conventions section.

### API surface
`POST /v1/cases` (202 + idempotency), `GET /v1/cases`, `GET /v1/cases/{id}`,
`GET /v1/cases/{id}/audit`, `GET /v1/cases/{id}/events`, `GET /v1/event-schemas`,
`POST /v1/cases/{id}/review`, `GET /healthz`. Role-gated per endpoint.

### Test coverage
- **8 of 10 ports have a shared contract test suite** in `tests/contracts/`:
  ingestion, triage, specialist, retrieval, synthesis, report, verification,
  guardrail — wired up in `test_port_contracts.py`. This is the mechanism
  [D14](07-risks-decisions.md) says should exist, and it exists. (`AuditPort` and
  `IdentityPort` don't have a generic contract suite yet — reasonable, since only
  one adapter exists for each today; nothing yet forces a second implementation to
  prove the abstraction.)
- `test_api.py` exercises the full state machine end-to-end: submission, triage,
  analysis, verification, synthesis, calibration, the degraded path, idempotent
  replay, tenant isolation, and the audit/event trails.
- 16 backend tests, all green as of this audit.

### Clinician dashboard ([apps/web](../apps/web))
A working React + TypeScript + Vite app exists with a case list, case detail view,
findings/differential/evidence rendering, and a confirm/edit/reject review form
gated on `status == AwaitingReview`. Present in the working tree; not yet reviewed
line-by-line as part of this audit round — verify independently before relying on
this entry.

## Fixed during this audit

**Degraded cases never reached the clinician with a report.** When no specialist
was registered for a modality, or a specialist returned zero findings, the
workflow set `status = Degraded` and an `escalation.reason`, but skipped report
composition entirely — jumping straight to `AwaitingReview` with `report: null`.
This contradicted [08](08-scalability-architecture.md)'s explicit requirement:
*"if a specialist dies, the case does not fail silently — it reaches the clinician
with an explicit 'analysis unavailable for X' flag."* The escalation reason was
visible in the API response, but the report panel a clinician actually reads had
nothing in it.

**Fix:** both `Degraded`-triggering branches in `workflow.py` now build a
`StructuredReport` (via a small `_degraded_report` helper) that states the
modality and the exact reason before transitioning, so `case.report` is always
populated by the time a case reaches `AwaitingReview`. (The existing `ReportPort.compose`
signature doesn't carry an escalation reason through in this baseline, so rather
than force that interface change under active concurrent development elsewhere in
the same files, the degraded path builds its report directly — same outcome, no
collision with in-flight port/composition work.) Added `report_ready`/`reason` to
the `workflow.degraded` event schema and locked the behavior in with new
assertions in `test_api.py`. 16 tests pass after the fix.

## Known gaps (intentional simplifications — "thin slice," not bugs)

Consistent with the "thicken later, don't retrofit" principle in
[08](08-scalability-architecture.md) and [05](05-roadmap.md). None of these need
fixing before Phase 1–2 continues; listed so nobody mistakes "simplified" for
"broken."

| Gap | Plan says | Currently | Tracked as |
|-----|-----------|-----------|------------|
| Message broker / durable workflow engine | Redis Streams/RabbitMQ/Kafka + LangGraph Postgres checkpointer ([08](08-scalability-architecture.md)) | In-process `threading.Thread` + `queue.Queue`; no crash-resume across process restarts | Next scaling step |
| Case/audit store | Postgres ([03](03-tech-stack.md)) | SQLite (`SQLiteCaseStore`) | Swap when multi-instance deployment starts |
| Orchestration | LangGraph ([D5](07-risks-decisions.md)) | Hand-written `while` loop over `CaseStatus` in `WorkflowRuntime._process_case` | Same state machine shape; migrate the *engine*, not the *design* |
| Identity | OIDC/SAML SSO ([09](09-security-identity-audit.md)) | Header-based principal read inline in `api/app.py` | Swap behind `IdentityPort` when real SSO lands |
| Verifier heterogeneity | A genuinely different model/provider from the specialist ([D6](07-risks-decisions.md)) | `StubVerificationAdapter` is rule-based, not model-backed | Wire a second model per [12 — Training Plan](12-training-plan.md) Vertical 1 |
| CXR specialist | MedGemma 1.5 ([04](04-data-models.md)) | `StubChestXRaySpecialistAdapter` is keyword-matching, not model-backed | Wire a real endpoint behind `SpecialistPort` |
| `ReportPort.compose` signature | Report reflects verification + escalation state | Only takes `(artifact, triage, findings, evidence, differential)` — no verification/escalation input, which is why the degraded-report fix above builds its report outside the normal reporter call | Extend the signature once the concurrent in-flight work on `composition.py`/`ports.py` settles |
| Observability | OpenTelemetry → Tempo/Jaeger, Prometheus/Grafana ([10](10-observability-mlops.md)) | Correlation IDs exist and propagate; no OTel export, metrics, or dashboards yet | Not started |
| MLOps | Model registry, eval gates, shadow/canary ([10](10-observability-mlops.md)) | Not started — no model has been trained yet | Starts with [12 — Training Plan](12-training-plan.md) Vertical 1 |
| Retrieval corpus | Vector DB (Qdrant/pgvector) over a real guideline corpus ([03](03-tech-stack.md)) | A few hand-written documents scored in-process | Real corpus + vector DB when RAG needs to scale past demo cases |
| Additional verticals | 8 modalities ([01](01-vision-scope.md)) | 1 (`chest_xray`); `ecg` is recognized by triage but has no registered specialist (exercises the `Degraded` path on purpose in tests) | Per [05 — Roadmap](05-roadmap.md) Phase 6+ |

## What's genuinely next (not yet started, not a stand-in)

- **CI pipeline** — no `.github/workflows/` or equivalent found. Tests exist and
  pass locally; nothing runs them automatically yet. Highest-leverage next step
  per [11](11-engineering-practices.md)'s Definition of Done.
- **Second specialist/vertical** — the real test of the hexagonal promise
  ([D3](07-risks-decisions.md), [D14](07-risks-decisions.md)) is adding one without
  touching `WorkflowRuntime`. Nothing has exercised that yet; `ecg` in triage is a
  placeholder, not a second adapter.
- **Real MedGemma / verifier model wiring** — no live model endpoint configured
  for either the specialist or the verifier yet.
- **This codebase is being actively developed by more than one contributor right
  now.** Before trusting this doc, re-run `pytest tests/ -q` and diff the port
  files against what's described here — it may already be stale.
