# 07 — Risks & Decisions

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Scope explosion** (8 verticals at once) | High | High | Ship 1 vertical end-to-end (CXR); shell is reusable. Enforce the "no orchestrator changes for vertical #2" test. |
| **Hallucinated findings** | High | Critical | Heterogeneous verifier + calibration + human confirm gate. Never a single-model answer. |
| **Data-access delays** (DUAs) | Medium | Medium | Start with fully-open sets (NIH CXR, BraTS). Begin PhysioNet credentialing in Week 0. |
| **3D compute cost** | Medium | Medium | Foundation-model embeddings / patch-based methods, not full retrain (CT-FM, MedSAM). |
| **"Looks like a device" liability** | Medium | High | Hard "research only" framing in UI + reports + paper. Human-confirm gate mandatory. |
| **PHI leak** | Low | Critical | De-identify in IngestionPort before anything else; DVC pointers only; PHI-safe infra. |
| **Ports abstraction leaks** (verticals need graph edits) | Medium | High | Treat M4 as a gate: if vertical #2 touches the orchestrator, fix the ports before #3. |
| **Silent OOD failure** (new scanner) | Medium | High | OOD detector in guardrail; subgroup performance reporting; per-site calibration. |
| **PHI leak via external LLM** | Medium | Critical | De-id-before-egress rule + single LLM-gateway egress point + BAA/self-hosted option (D11); every external call logged. |
| **LLM + GPU cost blowout** | Medium | Medium | Calibration-gated verification (D15); GPU scale-to-zero; caching; cost-per-case metric + alert. |
| **Case lost on crash/deploy** | Medium | High | Durable workflow checkpointing (D9); idempotent intake; dead-letter queue. |
| **Model drift / silent rot** | Medium | High | Input-drift detector + confirm/reject-rate monitoring by version & site; shadow before promote. |
| **Cross-tenant data leak** | Low | Critical | Row-level security + per-tenant keys + scoped tokens (D16); covered by contract/integration tests. |
| **Vendor / model lock-in** | Medium | Medium | Ports abstraction; heterogeneous providers already required (D6); registry-pinned models. |

## Decision log (ADRs)

Lightweight architecture decision records. Add one whenever a choice would be
expensive to reverse.

### D1 — First vertical: Chest X-ray + report
**Status:** Accepted · **Date:** 2026-07-07
Fully-open data (NIH ChestX-ray14, CheXpert), 2D, MedGemma 1.5 backbone, lowest
compute, fastest to a demo. Brain MRI (BraTS) is vertical #2.

### D2 — Primary goal: Startup product MVP
**Status:** Accepted · **Date:** 2026-07-07
Emphasis on a working clinician dashboard, human-in-loop UX, and a reusable shell.
Research/paper novelty (κ, ablations) is instrumented but not the driving goal.

### D3 — Full scope is all 8 verticals, delivered via the shell
**Status:** Accepted · **Date:** 2026-07-07
User confirmed all modalities are in scope. They are delivered as adapters behind
`SpecialistPort`, sequenced over time — not built simultaneously. The shell is the
product; verticals are content.

### D4 — Hexagonal (ports & adapters) architecture
**Status:** Accepted · **Date:** 2026-07-07
Mirrors the EduFX stack. Domain (orchestration/verification/calibration/synthesis)
depends only on ports; models and I/O are adapters. This is what makes D3 tractable.

### D5 — Orchestration via LangGraph, tools via MCP
**Status:** Accepted · **Date:** 2026-07-07
Stateful graph with a conditional verify loop (steps 4–5). Matches the cited
multi-agent clinical results.

### D6 — Verifier must be a heterogeneous model
**Status:** Accepted · **Date:** 2026-07-07
The critic is a different provider/model than the specialist/synthesis model.
Enforced by config in the `llm/` adapters. Primary hallucination defense.

### D7 — Novelty to lead with
**Status:** OPEN · **Decide by:** end of Phase 3
Candidates: cross-modal grounding (recommended visible hook), calibrated escalation
(trust story), verifier consensus (κ). The choice changes what Phases 4 & 7
instrument. See [05 — Roadmap](05-roadmap.md).

### D8 — Multi-language / edge deployment
**Status:** OPEN (deferred past MVP)
Sinhala/Tamil report generation + edge-deployable specialists for under-resourced
hospitals. Strong differentiator for the Sri Lanka context, but not MVP scope.

### D9 — Asynchronous, event-driven, durable workflow
**Status:** Accepted · **Date:** 2026-07-07
Medical inference is long-running and must not lose work, so a case is a
checkpointed **state machine over a message broker** with independently-scaled
worker pools — not a synchronous request/response. Corrects the original pipeline
reading. See [08 — Scalability](08-scalability-architecture.md).

### D10 — Walking-skeleton for every cross-cutting concern
**Status:** Accepted · **Date:** 2026-07-07
Security, audit, observability, MLOps, and testing are seeded *thin* in Phase 0–1
and thickened as we scale — never retrofitted into a synchronous prototype. See
[05 — Roadmap](05-roadmap.md).

### D11 — External vs. in-VPC / self-hosted LLM (the PHI-egress choice)
**Status:** OPEN · **Decide by:** before pilot
Only de-identified data may leave the PHI boundary. Options: (a) external LLM on
de-identified payloads via a controlled gateway, (b) in-VPC / BAA-covered LLM,
(c) self-hosted. Trade-offs: cost, latency, compliance. See [09 — Security](09-security-identity-audit.md).

### D12 — Immutable, hash-chained audit log from Phase 1
**Status:** Accepted · **Date:** 2026-07-07
Every consequential action recorded append-only and tamper-evident. Simultaneously
a compliance control, a debugging tool, and an enterprise-sales asset. See
[09 — Security](09-security-identity-audit.md).

### D13 — Durable execution engine: LangGraph checkpointer now, evaluate Temporal at scale
**Status:** OPEN (accepted-for-now) · **Date:** 2026-07-07
Start with LangGraph's Postgres checkpointer; revisit Temporal if checkpointing,
retries, or workflow visibility prove insufficient at scale. See [08](08-scalability-architecture.md).

### D14 — Contract tests per port as the extensibility guarantee
**Status:** Accepted · **Date:** 2026-07-07
Each port ships a shared contract test suite; an adapter is "done" when it passes.
This is what *mechanically enforces* the D3 promise that a new vertical never touches
the orchestrator. See [11 — Engineering Practices](11-engineering-practices.md).

### D15 — Calibration-gated verification
**Status:** Accepted · **Date:** 2026-07-07
Verifier intensity scales with uncertainty/stakes — full heterogeneous critique on
low-confidence / OOD / high-stakes findings, a lightweight check otherwise. One
mechanism serving cost, latency, and safety. See [08](08-scalability-architecture.md).

### D16 — Multi-tenant with per-site calibration
**Status:** Accepted · **Date:** 2026-07-07
Tenant/site is a first-class dimension; OOD thresholds and calibration are fit
*per site* (scanner/population variance). Onboarding a site = fitting calibration,
not retraining. See [08](08-scalability-architecture.md).
