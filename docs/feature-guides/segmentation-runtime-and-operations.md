# Segmentation, Runtime Posture, and Operations

## What this feature set does

This guide covers three implementation areas that support the core diagnostic
workflow:

- interactive segmentation refinement
- runtime readiness and model posture reporting
- lightweight operational observability

The relevant code lives in:

- `packages/core/src/aegis_dx/segmentation.py`
- `packages/core/src/aegis_dx/models/medsam_backend.py`
- `packages/core/src/aegis_dx/model_readiness.py`
- `packages/core/src/aegis_dx/metrics.py`
- `packages/core/src/aegis_dx/queueing.py`
- `packages/core/src/aegis_dx/api/app.py`
- `apps/web/src/App.tsx`

## Interactive segmentation refinement

The segmentation feature lets a clinician-side user submit:

- an artifact URI
- a box prompt

and receive back a refined segmentation mask summary.

This is currently exposed through:

- `POST /v1/segmentations/refine`
- the segmentation panel in the dashboard

## Why segmentation is a separate port

Segmentation is not modeled as a specialist finding generator.
Instead, it has its own contract:
`SegmentationRefinementPort`.

That makes sense because segmentation is doing a different job:

- specialists produce diagnostic findings
- segmentation refines a spatial mask from a user prompt

Keeping them separate avoids overloading the meaning of the specialist layer.

## How the MedSAM adapter works

`MedSAMSegmentationRefinerAdapter`:

1. resolves a readable local image path
2. ensures image libraries are available
3. opens the image
4. validates the prompt box against image bounds
5. runs the MedSAM backend
6. converts the binary mask into a compact result shape

The output includes:

- artifact URI
- model version
- mask shape
- number of positive pixels
- run-length encoded mask (`rle`)

This is a useful engineering choice because sending a compact mask summary is
much lighter than sending raw full-size arrays over the API.

## Why local artifact paths are used

The current segmentation path expects a readable local image path.

That may feel unusual if you are used to cloud object stores, but it makes sense
for the current stage because:

- it supports local experimentation
- it avoids adding object-store complexity too early
- it enables truly local pretrained execution

It is a good example of staged engineering maturity:
keep the interface clean now, and upgrade the storage backing later.

## Runtime posture and model status

The model status feature is one of the most practical pieces of operational UX
in the project.

`GET /v1/model-status` reports for each major model-backed component:

- component name
- backend type
- model version
- execution mode
- whether it is configured
- whether fallback is available
- whether the runtime appears ready
- a reason string explaining that readiness state

This is extremely helpful because AI systems often fail in confusing ways when
their dependencies are missing. This endpoint gives a structured answer to:

> what is actually configured and runnable right now?

## Why readiness is not the same as health

The runtime posture endpoint intentionally does not behave like a deep network
health checker.

Instead, it answers questions like:

- is a local dependency installed?
- is a checkpoint configured?
- is a remote endpoint value present?

This makes it safer and easier to use from the UI without turning it into a noisy
operational probe.

That distinction is worth remembering:

- **health** asks “is the service alive right now?”
- **readiness posture** asks “is this component configured in a usable mode?”

## Metrics

The metrics system is intentionally small but useful.

`InMemoryMetricsRegistry` supports:

- counters
- simple observations/histogram-like sums and counts
- Prometheus text rendering

The middleware records HTTP request counts and durations, and the workflow
records domain-level operational counters such as:

- submitted cases
- started/completed workflow cases
- model findings
- escalations
- re-query rounds
- human review actions

This is a strong pattern for early-stage systems:
instrument the essential business/operational events first before investing in a
full observability platform.

## Queueing and deployment shape

Operations are also shaped by queueing decisions.

The project supports:

- in-process queueing for easy local work
- Redis Streams for deployment-shaped, cross-process queueing

That means the system can graduate from “single process demo” to “API and worker
separated” without rewriting the workflow core.

This is the same general pattern used elsewhere in the repo:
stable contract first, swappable infrastructure second.

## Why this feature set matters for learning

It teaches that production shape is not only about the ML logic.
A real intelligent product also needs:

- runtime introspection
- bounded observability
- safe local-vs-remote execution paths
- infrastructure seams that let the system evolve gradually

## What to remember

This feature set shows how the repo handles the “operational edges” of an AI
product:

- interactive model-assisted refinement
- explicit runtime capability reporting
- lightweight but useful metrics
- queueing choices that support both local development and future deployment
