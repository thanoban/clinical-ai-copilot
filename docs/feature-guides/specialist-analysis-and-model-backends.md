# Specialist Analysis and Model Backends

## What this feature does

This feature turns a routed case into modality-specific findings.

The current implemented specialists are:

- chest X-ray
- ECG

The relevant code lives in:

- `packages/core/src/aegis_dx/specialists.py`
- `packages/core/src/aegis_dx/ecg_specialists.py`
- `packages/core/src/aegis_dx/models/`
- `packages/core/src/aegis_dx/imaging.py`
- `packages/core/src/aegis_dx/api/app.py`

## The architectural pattern

Both imaging and ECG analysis are built around the same contract:
`SpecialistPort`.

That port says:

> given a normalized artifact and triage context, return `Finding[]`.

This is powerful because it standardizes very different clinical modalities into
one workflow-facing shape.

The workflow does not need separate branches for:

- image specialists,
- ECG specialists,
- remote HTTP model deployments,
- or local pretrained inference.

It just asks the registry for the right specialist and calls `analyze(...)`.

## Why the registry matters

`SpecialistRegistry` maps `modality -> specialist adapter`.

That means routing is a two-step process:

1. triage predicts the modality
2. the registry resolves the adapter for that modality

This is simpler and cleaner than hard-coding modality-specific logic directly in
the workflow.

It also makes “add a new vertical” mostly a registration exercise.

## The chest X-ray implementation

There are multiple CXR execution paths:

### 1. Stub specialist

`StubChestXRaySpecialistAdapter` is a deterministic fallback.
It reads de-identified text and emits safe, simple findings based on keywords
like `pneumonia` or `effusion`.

Why keep a stub when real model work exists?

- it keeps development/test workflows reliable
- it gives deterministic behavior for contract tests
- it prevents the whole case from failing when real model infrastructure is not ready

### 2. Remote model-backed specialist

`ModelBackedChestXRaySpecialistAdapter` sends a structured HTTP request to a
configured endpoint.

The payload includes:

- selected model id/version
- modality and region
- urgency
- de-identified report text
- optional artifact URI

This adapter represents the “production-like” deployment pattern:
the API runtime does not embed the actual model; it calls a separate model
service.

### 3. Local pretrained specialist

`HFTorchXRayVisionSpecialistAdapter` runs a local pretrained classifier through
`TorchXRayVisionClassifier`.

This path is educational because it shows how a true in-process model can still
conform to the exact same `SpecialistPort` contract.

Instead of calling HTTP, it:

- resolves a readable local image path,
- runs the classifier,
- converts pathology scores into standard `Finding` objects.

The underlying method is not “LLM reasoning.” It is classical image-model
inference wrapped into the diagnostic shell.

## The ECG implementation

The ECG side follows the same pattern but uses signal-oriented assumptions.

### Stub ECG specialist

`StubECGSpecialistAdapter` is the safe fallback.
It looks for infarction-related language and emits high-level ECG findings.

### Model-backed ECG specialist

`ModelBackedECGSpecialistAdapter` calls a remote endpoint intended to represent
an ECG model trained on PTB-XL-like data.

The key lesson here is consistency:
even though the clinical input type is different, the adapter still returns the
same normalized `Finding` structure the workflow expects.

That means the system’s shell stays uniform across modalities.

## Why payload normalization matters

Every specialist adapter builds a structured payload instead of sending the raw
internal case object.

That has several benefits:

- it defines a stable boundary with remote model services
- it limits what leaves the workflow process
- it keeps request shapes readable in tests
- it makes future model-service ownership cleaner

You can think of this as a mini API contract between the product shell and the
model-serving layer.

## Why fallbacks are so important

Every model-backed specialist falls back instead of failing hard when:

- no endpoint is configured,
- the HTTP call fails,
- the response is malformed,
- or the parsed findings are unusable.

This is not just resilience engineering. It supports the product’s research
workflow:

- the shell can be exercised before production model hosting is ready
- the system can still demonstrate end-to-end behavior
- failures are transparent instead of silent

Importantly, fallback does **not** mean “pretend the real model succeeded.”
It means “use a safe substitute path that still expresses the same contract.”

## What a `Finding` really represents

A finding is a normalized clinical claim with:

- `claim`
- `locus`
- `probability`
- `source_agent`
- `model_version`
- optional `saliency_ref`

This is an important teaching point:
the specialist output is not a final report. It is structured evidence for later
workflow stages.

That is why the shell can:

- verify it,
- compare it,
- synthesize it,
- escalate it,
- and render it differently in the dashboard.

## The technology decisions behind this feature

### HTTP-backed model adapters

These are chosen because many real ML deployments run outside the API process.
It keeps model hosting flexible and avoids forcing heavyweight runtime
dependencies into the API container.

### Local pretrained wrappers

These exist for realism and experimentation. They let the repo demonstrate
actual model execution without needing every deployment to have a live external
endpoint.

### Registry pattern

The registry is a clean way to keep modality routing open-ended. It avoids
switch-statements scattered across the codebase.

## What to remember

This feature teaches the project’s vertical-expansion strategy:

- every modality becomes a `SpecialistPort` adapter
- real and fallback paths can coexist
- the workflow does not change when the specialist implementation changes
- findings are intermediate structured outputs, not final answers
