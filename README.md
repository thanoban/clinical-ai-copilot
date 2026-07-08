# Aegis-Dx — Multi-Agent Multimodal Diagnostic Copilot

> **Status:** Planning · **Type:** Startup product MVP · **First vertical:** Chest X-ray + report

Ingest any medical artifact (image + report + signal), route it to specialist
agents, cross-verify their claims with a heterogeneous critic, and return a
**confidence-scored, evidence-linked draft assessment** for a clinician to
confirm.

> ⚠️ **Research prototype — NOT for clinical use.** Every output is a *draft for a
> licensed clinician to confirm or reject*. Nothing this system produces is
> clinically actionable on its own. This framing is a product requirement, not a
> disclaimer to bolt on later. See [docs/06-compliance-safety.md](docs/06-compliance-safety.md).

---

## The core bet

The product is **not** any single detector. It is the **reusable multi-agent
shell**:

- an **orchestrator** that classifies input and routes to specialists,
- a **verifier/critic** (a *different* model) that challenges every finding,
- a **synthesis + reporter** layer that fuses everything into a calibrated draft,
- a **clinician dashboard** with evidence overlays and a mandatory human-confirm step.

Each diagnostic **vertical** (chest X-ray, brain MRI, ECG, lung CT, histopathology,
echo, dermatology) is just an **adapter behind a port**. Ship the shell once with
one vertical end-to-end; every additional vertical reuses the shell. This maps
directly onto the EduFX hexagonal (ports & adapters) pattern.

## MVP definition (v1 "done")

One vertical — **chest X-ray + free-text report** — flowing through the *entire*
pipeline: ingest → de-identify → triage → retrieve → analyze → verify →
synthesize → calibrate → report → **clinician confirms in the dashboard** →
feedback logged. The shell, dashboard, and human-in-loop loop are production-shaped;
adding vertical #2 must not require touching the orchestrator.

## Engineering principles (scalable + professional by construction)

- **Async, durable, event-driven.** A case is a checkpointed state machine over a
  queue, not a blocking request — so slow 3D inference and crashes never lose work or
  stall the system. [08](docs/08-scalability-architecture.md)
- **Walking skeleton, not bolt-on.** SSO/RBAC, an immutable audit log, tracing, a
  model registry, and contract tests exist from Phase 1 — thin at first, thickened as
  we scale. Nothing critical is retrofitted. [05](docs/05-roadmap.md)
- **Ports enforce extensibility.** Every vertical is an adapter that must pass its
  port's shared contract test — that is what *guarantees* adding a vertical never
  touches the orchestrator. [11](docs/11-engineering-practices.md)
- **Only de-identified data leaves the PHI boundary.** External model calls route
  through one controlled egress gateway, or stay in-VPC / self-hosted. [09](docs/09-security-identity-audit.md)
- **Multi-tenant with per-site calibration** — onboarding a hospital means fitting
  its calibration, not retraining a model. [08](docs/08-scalability-architecture.md)

## Documentation map

| Doc | What's in it |
|-----|--------------|
| [01 — Vision & Scope](docs/01-vision-scope.md) | Vision, scope matrix, MVP boundary, vertical sequencing, non-goals |
| [02 — Architecture](docs/02-architecture.md) | Why multi-agent, agent roster, the 10-step pipeline, the verify loop, prior art |
| [03 — Tech Stack](docs/03-tech-stack.md) | Stack choices, hexagonal ports/adapters mapping, proposed repo layout |
| [04 — Data & Models](docs/04-data-models.md) | Datasets per vertical (open vs. credentialed), foundation models, access plan |
| [05 — Roadmap](docs/05-roadmap.md) | Phased build plan, milestones, MVP vs. later |
| [06 — Compliance & Safety](docs/06-compliance-safety.md) | Human-in-loop, PHI/de-id, SaMD framing, bias, failure transparency |
| [07 — Risks & Decisions](docs/07-risks-decisions.md) | Risk register + decision log (ADRs) |
| [08 — Scalability & Architecture](docs/08-scalability-architecture.md) | Async/durable runtime, tiers, case state machine, multi-tenancy, resilience, NFRs/SLOs, cost |
| [09 — Security, Identity & Audit](docs/09-security-identity-audit.md) | SSO/RBAC, immutable audit log, secrets, encryption, PHI-egress rule, threat model |
| [10 — Observability & MLOps](docs/10-observability-mlops.md) | Tracing/metrics/logs, model registry, eval gates, shadow/canary, drift monitoring |
| [11 — Engineering Practices](docs/11-engineering-practices.md) | Test pyramid + contract tests, CI/CD, environments, IaC, API conventions, IEC 62304 |
| [12 — Training Plan](docs/12-training-plan.md) | Per-vertical training recipe: splits, preprocessing, loss/imbalance, metrics, compute, promotion gates |
| [13 — Agent Build Plan](docs/13-agent-build-plan.md) | Build order for every agent in the roster, I/O contracts, prompt strategy, acceptance/contract tests |

## Novelty candidates (pick one to lead with)

Multi-agent medical AI is crowded — "we used agents" is not a differentiator.
Candidates, in priority order for a startup story:

1. **Cross-modal grounding** — link a text finding ("mass in RUL") to the exact
   voxel region *and* the corroborating signal. Evidence-traceable, not just an answer.
2. **Calibrated escalation** — explicit uncertainty + OOD routing so the system
   knows when to defer. Measurable via selective-prediction curves.
3. **Heterogeneous verifier consensus** — formal agreement metrics (Cohen's κ)
   between different models as the primary hallucination defense.

See [docs/01-vision-scope.md](docs/01-vision-scope.md) for how these shape the roadmap.
