# System Foundations

## What this feature area is

The system foundations are the shared design rules that every feature in the
project is built on. If you understand this layer, the rest of the codebase
stops feeling like a pile of unrelated modules and starts feeling like one
coherent product.

The core foundation is **hexagonal architecture**:
the workflow depends on interfaces called ports, and concrete behavior is
supplied by adapters. That means the workflow does not care whether a
specialist is:

- a tiny stub,
- a remote HTTP model,
- a local pretrained model,
- or a future production deployment.

It only cares that the adapter satisfies the expected contract.

## The main idea behind the architecture

The repo is designed around this belief:

> the reusable value is the workflow shell, not any single specialist model.

That is why the system is split into:

- **domain models** in `domain.py`
- **contracts** in `ports.py`
- **runtime orchestration** in `workflow.py`
- **HTTP composition** in `api/app.py`
- **concrete model/content adapters** in modules like `specialists.py`,
  `ecg_specialists.py`, `composition.py`, `trust.py`, and `segmentation.py`
- **frontend review UX** in `apps/web`

This separation keeps feature growth manageable. A new vertical should mainly
mean “write or register a new adapter,” not “rewrite the orchestrator.”

## The domain model

The center of the system is the `CaseRecord` shape in
`packages/core/src/aegis_dx/domain.py`.

That object is the persistent truth for a diagnostic case. It carries:

- identity fields like `case_id`, `trace_id`, `tenant_id`, and `site_id`
- workflow state in `status`
- input context in `artifact`
- routed metadata like `modality`, `region`, and `urgency`
- diagnostic outputs like `findings`, `verification`, `differential`, and `report`
- trust/safety outputs like `escalation`, `consensus_kappa`,
  `complexity_tier`, `verification_round`, `reflexion_revisions`,
  and `reflexion_incomplete`
- human finalization in `human_review`

This is important because the system is **stateful**. It does not compute one
answer and throw the context away. Instead, a case evolves through stages and
the record accumulates the outputs of those stages.

## The ports

The most educational file in the backend is
`packages/core/src/aegis_dx/ports.py`.

It tells you what the system believes its stable concepts are:

- `IngestionPort`
- `TriagePort`
- `SpecialistPort`
- `RetrievalPort`
- `SynthesisPort`
- `ReportPort`
- `VerificationPort`
- `GuardrailPort`
- `SegmentationRefinementPort`
- `AuditPort`
- `IdentityPort`
- `MetricsPort`
- `CaseStorePort`

These are not abstract for the sake of abstraction. Each one marks a place
where the project expects change:

- the ingestion logic can become more clinical and less regex-based
- triage can move from rules to model-based routing
- specialists can swap between stub, remote, or local model backends
- retrieval can move from in-code snippets to a vector store
- verification can move from rules to a true independent critic deployment
- storage can move between SQLite and Postgres
- queueing can move between in-process and Redis

The port list is basically a map of where future product evolution is expected.

## Why the composition root matters

`packages/core/src/aegis_dx/api/app.py` is not just the HTTP layer. It is also
the **composition root**, meaning it decides which real adapters are wired into
the runtime.

That file answers questions like:

- Should the case store be SQLite or Postgres?
- Should queueing be in-process or Redis-backed?
- Should the CXR specialist be local or remote?
- Which verifier is allowed to run?
- Is the heterogeneous-verifier rule satisfied?
- Which synthesis adapter is wrapped with reflexion?
- Which security and metrics adapters are active?

This is a deep architectural point:
the runtime stays generic because all environment-specific choices are made at
the edge.

## Why the frontend also fits the same architecture

The dashboard in `apps/web` is not a separate toy app. It is another adapter
layer, just on the UI side.

It mirrors the backend contracts by:

- rendering `CaseRecord` fields directly
- using the existing route shapes instead of inventing new frontend-only APIs
- exposing the human review gate as a first-class feature
- showing the system’s evidence and trust outputs rather than hiding them

That makes the UI educational too:
it teaches what the backend thinks is important enough to expose to a clinician.

## The main technologies and why they were chosen

### FastAPI

FastAPI is used for the backend because it is lightweight, strongly typed,
and good at turning domain models into HTTP contracts quickly. It fits an MVP
that wants clean request/response models without the weight of a larger web
framework.

### Pydantic

Pydantic models are used because they turn domain objects into:

- validated runtime data,
- serializable API payloads,
- shared backend truth for tests and docs.

The code relies on them heavily for safe shape handling.

### React + TypeScript + Vite

The frontend stack is practical for a product slice like this:

- React provides stateful UI composition
- TypeScript keeps the UI aligned with backend data shapes
- Vite gives fast local iteration and clean production builds

### Protocol-based interfaces

Python `Protocol` types are used instead of abstract base classes because they
keep the code flexible. An adapter only has to behave correctly; it does not
have to inherit from one rigid base class.

That matters in a repo where experimentation with model backends is expected.

## What to remember

If you only remember three things from this file, remember these:

1. The project’s unit of design is the **case workflow**, not the request.
2. The system’s extensibility comes from **ports + adapters**.
3. The backend, queueing, models, audit trail, and frontend are all parts of
   one reusable diagnostic shell.
