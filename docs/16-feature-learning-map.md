# 16 — Feature Learning Map

This document is a guided entry point for learning how the current Aegis-Dx
codebase works in practice. It is not a roadmap and it is not a status audit.
Instead, it explains the implemented feature areas in a way that helps you
reconstruct the system architecture, the method choices, and the technology
tradeoffs after building parts of the project with agent assistance.

Use this file as the index, then read the feature guides in the order below.

## Suggested reading order

1. **[System Foundations](feature-guides/system-foundations.md)**  
   Learn the domain model, the ports-and-adapters structure, and how the repo is
   split between API, workflow, adapters, and UI.

2. **[Case Lifecycle and Orchestration](feature-guides/case-lifecycle-and-orchestration.md)**  
   Learn how a case moves through the workflow, why the state machine exists,
   and how queueing, persistence, and idempotency fit together.

3. **[Specialist Analysis and Model Backends](feature-guides/specialist-analysis-and-model-backends.md)**  
   Learn how the CXR and ECG specialists are built, why stub and model-backed
   adapters coexist, and how local versus remote model execution is handled.

4. **[Verification, Consensus, and Guardrails](feature-guides/verification-consensus-and-guardrails.md)**  
   Learn the critic model pattern, the bounded re-query loop, the consensus
   score, and how escalation decisions are made.

5. **[Security, Identity, and Audit Trails](feature-guides/security-identity-and-audit-trails.md)**  
   Learn how tenant isolation, role checks, audit chaining, and lifecycle events
   are implemented today.

6. **[Clinician Dashboard and Human Review](feature-guides/clinician-dashboard-and-human-review.md)**  
   Learn how the frontend maps onto the backend API and how the final
   confirm/edit/reject gate is enforced.

7. **[Segmentation, Runtime Posture, and Operations](feature-guides/segmentation-runtime-and-operations.md)**  
   Learn the interactive segmentation feature, runtime-readiness reporting,
   metrics, and the deployment-shape infrastructure that supports the workflow.

## How to use these guides well

- Read each guide with the referenced source files open beside it.
- Move from abstract to concrete:
  start with the "why", then the data shape, then the adapter/runtime code.
- Compare the guides with:
  - [02 — Architecture](02-architecture.md)
  - [03 — Tech Stack](03-tech-stack.md)
  - [14 — Implementation Status](14-implementation-status.md)
  - [15 — Agentic Architecture](15-agentic-architecture.md)
- Treat these guides as **learning notes about the current implementation**.
  If code and prose disagree, the code wins.

## What this set is trying to teach

These guides are meant to answer questions like:

- What are the real implemented features, not just planned ones?
- Why was a port used here instead of a direct function call?
- Where does a case start, and what transforms it before it reaches the UI?
- How do the trained-model paths coexist with safe fallbacks?
- How does the verifier differ from the specialist in both architecture and purpose?
- Where is human authority enforced, and how is that recorded?
- How do observability and security concerns flow through normal product features?

## Learning mindset for this repo

The most important thing to understand is that this project is **not** “one ML
model plus a dashboard.” It is a reusable diagnostic shell made from several
cooperating layers:

- domain contracts,
- workflow orchestration,
- specialist adapters,
- verification and guardrails,
- security and audit seams,
- persistence and queueing,
- clinician-facing review UX.

Once that mental model clicks, the repo becomes much easier to reason about.
