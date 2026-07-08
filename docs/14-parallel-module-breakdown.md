# 14 — Parallel Module Breakdown

This doc turns the current plan and correction notes into **parallel work modules**
that can be continued in separate Codex tabs with minimal overlap.

There is **no dedicated `corrections.md` file** in the repo right now. This split is
based on:

- [05 — Roadmap](05-roadmap.md)
- [09 — Security, Identity & Audit](09-security-identity-audit.md)
- [12 — Training Plan](12-training-plan.md)
- [13 — Agent Build Plan](13-agent-build-plan.md)

---

## What is already finished

The current backend walking skeleton already has:

- FastAPI intake/review API with tenant-scoped header auth
- correlation IDs and lifecycle event stream
- append-only hash-chained audit log
- idempotent intake (`Idempotency-Key`)
- port-backed ingestion, triage, specialist routing, retrieval, synthesis, reporting
- port-backed verification and guardrail logic
- contract tests for all current ports
- API/integration tests for the current end-to-end backend flow

Core implementation lives under:

- `packages/core/src/aegis_dx/`
- `tests/`

---

## Parallel rule

To avoid collisions, each tab should mostly stay inside **its own file set**.

- If two tabs both edit `workflow.py` or `api/app.py`, expect merge work.
- If a tab only edits its own adapter/module files plus tests/docs, it should merge cleanly.

Recommended order for safe parallelism:

1. Backend model adapters
2. Orchestrator/runtime hardening
3. Frontend dashboard
4. Security/identity hardening
5. Training/eval infrastructure

---

## Module A — Real CXR Specialist

**Goal:** Replace the stub CXR specialist with a real model-backed adapter.

**Why this matters:** This is the biggest remaining step from “backend skeleton” to
“actual diagnostic pipeline.”

**Primary files:**

- `packages/core/src/aegis_dx/specialists.py`
- new model-serving helper files under `packages/core/src/aegis_dx/`
- `tests/contracts/specialist_contract.py`
- `tests/test_api.py`
- optionally `docs/12-training-plan.md`

**What to build:**

1. Add a model-backed CXR specialist adapter next to the stub.
2. Keep the `SpecialistPort` contract unchanged.
3. Normalize model output into `Finding[]`.
4. Preserve `locus`, `probability`, `source_agent`, `model_version`, `saliency_ref`.
5. Keep graceful degraded behavior on timeout/failure.

**Acceptance:**

- contract tests still pass
- API path still returns schema-valid findings
- injected failure still moves case to degraded mode

**Good parallel-tab prompt:**

`Implement the real chest X-ray specialist adapter behind SpecialistPort without changing the workflow contract. Keep degraded fallback behavior and add tests.`

---

## Module B — Retrieval + Knowledge Layer Hardening

**Goal:** Move from stub evidence snippets to a real retrieval-ready structure.

**Why this matters:** Phase 3 depends on evidence-linked output, not just findings.

**Primary files:**

- `packages/core/src/aegis_dx/composition.py`
- new retrieval helper/index files
- `packages/core/src/aegis_dx/ports.py`
- `tests/contracts/retrieval_contract.py`
- `tests/test_api.py`
- `docs/13-agent-build-plan.md`

**What to build:**

1. Add a real retrieval adapter shape that can later plug into Qdrant/pgvector.
2. Keep `RetrievalPort` stable.
3. Make snippets cite source, type, and URI cleanly.
4. Prepare for golden retrieval tests.

**Acceptance:**

- retrieval contract remains stable
- retrieved evidence appears in `CaseRecord`
- report links still render from evidence URIs

**Good parallel-tab prompt:**

`Harden the RetrievalPort implementation so it is ready for a real guideline corpus later. Keep the existing API contract, improve evidence structure, and add tests.`

---

## Module C — Verifier + Guardrail Hardening

**Goal:** Upgrade the trust layer from stub logic toward heterogeneous verification and richer escalation rules.

**Why this matters:** This is the remaining backend trust story from Phase 4.

**Primary files:**

- `packages/core/src/aegis_dx/trust.py`
- `packages/core/src/aegis_dx/ports.py`
- `packages/core/src/aegis_dx/event_schemas.py`
- `tests/contracts/verification_contract.py`
- `tests/contracts/guardrail_contract.py`
- `tests/test_api.py`

**What to build:**

1. Strengthen verification output structure.
2. Add richer disagreement flags.
3. Add simple OOD-style escalation hooks.
4. Keep guardrail decisions explicit and testable.
5. Preserve event payload compatibility where possible.

**Acceptance:**

- low-confidence findings escalate
- evidence-missing cases escalate
- safe, evidence-backed cases do not escalate
- lifecycle event payloads remain schema-valid

**Good parallel-tab prompt:**

`Improve the VerificationPort and GuardrailPort implementations without changing the public case API shape. Add more realistic trust-layer behavior and tests.`

---

## Module D — Orchestrator Runtime Hardening

**Goal:** Replace the in-process queue/thread skeleton with a more durable orchestration boundary.

**Why this matters:** This is the biggest remaining backend infrastructure gap from the roadmap.

**Primary files:**

- `packages/core/src/aegis_dx/workflow.py`
- `packages/core/src/aegis_dx/store.py`
- `packages/core/src/aegis_dx/api/app.py`
- new runtime/checkpoint helper files
- `tests/test_api.py`
- new integration tests
- `docs/08-scalability-architecture.md`

**What to build:**

1. Isolate the queue/worker runtime behind a cleaner interface.
2. Prepare the workflow for a broker/checkpointer later.
3. Add stronger integration tests for crash/degraded/replay paths.
4. Avoid rewriting business logic contracts.

**Acceptance:**

- current API still works
- tests cover restart/replay or equivalent durable semantics
- workflow file gets simpler, not more tangled

**Parallel caution:** This module will likely touch `workflow.py`, so it should not
run in parallel with other tabs editing the same file.

**Good parallel-tab prompt:**

`Refactor the workflow runtime toward a durable orchestrator boundary without breaking the current API or port contracts. Prefer cleaner runtime seams over adding more inline logic.`

---

## Module E — Clinician Dashboard Frontend

**Goal:** Build the first real user-facing dashboard for the current backend.

**Why this matters:** This is the biggest product-facing gap after the backend shell.

**Primary files:**

- likely new `apps/web/` tree
- shared frontend types if introduced
- API client files
- dashboard tests
- `docs/08-scalability-architecture.md`
- `docs/09-security-identity-audit.md`

**What to build:**

1. Case list view
2. Case detail view
3. findings + evidence + escalation display
4. confirm/edit/reject workflow
5. visible research-only framing

**Acceptance:**

- can list cases
- can open a case
- can review and submit confirm/edit/reject
- disclaimer is visible

**Good parallel-tab prompt:**

`Scaffold the clinician dashboard frontend against the current backend API. Start with case list, case detail, findings/evidence rendering, and confirm-edit-reject actions.`

---

## Module F — Security / Identity Hardening

**Goal:** Move the auth/security layer from header stub toward a real security boundary.

**Why this matters:** [09 — Security, Identity & Audit](09-security-identity-audit.md)
contains the biggest “correction” from the original plan: strict PHI-safe egress and real identity controls.

**Primary files:**

- `packages/core/src/aegis_dx/api/app.py`
- new identity/auth helper modules
- `packages/core/src/aegis_dx/store.py`
- `tests/test_api.py`
- `docs/09-security-identity-audit.md`

**What to build:**

1. Replace raw header auth assumptions with a cleaner auth seam.
2. Prepare for OIDC/SAML integration later.
3. Strengthen tenant scoping at the data layer.
4. Add LLM-egress policy hooks if/when external model calls are introduced.

**Acceptance:**

- existing tenant isolation remains green
- auth seam is cleaner and more realistic
- no PHI-unsafe shortcuts are introduced

**Parallel caution:** This module may overlap with runtime and frontend tabs if they
also touch auth behavior.

**Good parallel-tab prompt:**

`Refactor the current header-based auth stub into a cleaner IdentityPort-driven security seam while preserving the current testable tenant isolation behavior.`

---

## Module G — Training / Eval / Registry Infrastructure

**Goal:** Turn the training docs into runnable repo structure for data splits, evals, and model promotion.

**Why this matters:** The backend is ready for better adapters, but model lifecycle discipline still needs repo structure.

**Primary files:**

- new `eval/`
- new `models/`
- new `data/splits/`
- new training helper scripts
- `docs/12-training-plan.md`
- `docs/10-observability-mlops.md`

**What to build:**

1. Create split file format and placeholder tracked examples.
2. Create eval harness skeleton for CXR.
3. Create model metadata/registry-ready structure.
4. Add validation rules around model version and eval outputs.

**Acceptance:**

- repo has a concrete eval/training layout
- split/version structure is documented and testable
- specialist adapters can point to model metadata cleanly

**Good parallel-tab prompt:**

`Create the initial eval and model-registry repo structure described in the training plan, focused on CXR first. Keep it code-and-artifact structure, not a paper plan.`

---

## Best parallel split right now

If you want to continue in multiple tabs immediately, this is the safest split:

1. **Tab 1:** Module A — Real CXR specialist
2. **Tab 2:** Module E — Clinician dashboard frontend
3. **Tab 3:** Module G — Training/eval/repo structure
4. **Tab 4:** Module F — Security/auth seam cleanup

This avoids too many tabs touching `workflow.py` at the same time.

---

## Module dependencies

- Module A depends on the current port/contracts only.
- Module B depends lightly on current composition ports.
- Module C depends on current trust ports.
- Module D depends on almost everything and should usually be done alone.
- Module E mostly depends on stable API responses.
- Module F can proceed in parallel if it avoids changing route shapes.
- Module G is mostly independent of the live workflow code.

---

## Suggested next owner flow

If **you** want to continue from another tab with the least merge pain:

- pick **Module E** if you want visible product progress
- pick **Module A** if you want stronger diagnostic realism
- pick **Module G** if you want model/training groundwork
- pick **Module F** if you want platform/security depth

