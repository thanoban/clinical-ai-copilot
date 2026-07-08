# 05 — Roadmap

Phase durations are rough (solo/small-team, weeks). The ordering matters more than
the numbers. **The shell is built once (Phases 1–5); verticals after that reuse it.**
Per-agent build steps and acceptance tests: [13 — Agent Build Plan](13-agent-build-plan.md).
Per-model training recipes: [12 — Training Plan](12-training-plan.md).

| Phase | Deliverable | Weeks |
|-------|-------------|-------|
| **0** | Scope to CXR vertical · secure open datasets · PHI/ethics plan · repo scaffold · **CI + IaC + observability + SSO/RBAC walking skeleton** | 1–2 |
| **1** | Ingestion + de-identification + triage agent · **async workflow + queue + durable checkpointing + append-only audit log + correlation-ID tracing** | 1–2 |
| **2** | First imaging specialist: CXR via MedGemma → findings + saliency + locus | 2–3 |
| **3** | LangGraph orchestrator + RAG + synthesis + reporter (findings → draft) | 2–3 |
| **4** | Verifier/critic (heterogeneous model) + calibration/guardrail (confidence, OOD, escalation) | 1–2 |
| **5** | Clinician dashboard: viewer + overlays + **confirm/edit/reject** + feedback log | 2 |
| **6** | Vertical #2 (Brain MRI/BraTS), then #3 (ECG) — **reusing the shell** | 2–3 each |
| **7** | Evaluation, ablations, subgroup reporting, write-up | 2 |

## Continuous tracks (not phases — they run from Phase 0 onward)

These are **walking skeletons** ([08](08-scalability-architecture.md)): thin in the
MVP, thickened as you scale. None is ever a "later phase."

- **Security & audit** — SSO/RBAC stub + append-only audit log from Phase 1; hardened
  (secrets, egress control, threat model) before pilot. [09](09-security-identity-audit.md)
- **Observability** — correlation-ID tracing, core metrics, SLO alerts from Phase 1;
  full dashboards as load grows. [10](10-observability-mlops.md)
- **MLOps** — model registry + eval-gate-in-CI from the first model (Phase 2);
  shadow/canary + drift monitoring once there's live traffic. [10](10-observability-mlops.md)
- **Testing & delivery** — contract tests per port from Phase 1; CI type-check +
  security scans throughout. [11](11-engineering-practices.md)

## Milestones

- **M0 — Platform walking skeleton (end Phase 1):** a trivial case flows through the
  async workflow (queue → durable orchestrator → worker → result), authenticated,
  traced end-to-end, and audit-logged — *before* any real model exists. Proves the
  spine so every later feature slots into a scalable, observable shell.
- **M1 — Artifact in, structured out (end Phase 3):** a CXR + report produces a
  ranked differential with per-finding confidence. No dashboard yet; verify via API.
- **M2 — Trustworthy draft (end Phase 4):** every finding is challenged by a
  heterogeneous critic; low-confidence/OOD cases auto-escalate. This is the point
  where the system is *honestly* useful rather than confidently wrong.
- **M3 — MVP (end Phase 5):** the full loop including the clinician confirm gate
  and feedback logging. **This is the shippable v1.**
- **M4 — Shell proven (Phase 6):** vertical #2 lands *without touching the
  orchestrator graph*. If it requires graph changes, the ports abstraction failed —
  fix that before adding #3.

## What ships in MVP vs. later

**MVP (M3):** CXR vertical, full pipeline, dashboard, human-in-loop, open data,
heterogeneous verifier, calibrated escalation, feedback *logging*.

**Later:** additional verticals (MRI/ECG/CT/path/echo/derm), credentialed datasets,
the active-learning retraining loop (Phase-10 "LEARN"), multi-language
(Sinhala/Tamil) reports, edge-deployable specialist models for under-resourced
settings.

## Pick the novelty lead early (affects Phase 4 & 7)

The novelty you lead with changes what you instrument from Phase 4 onward:

- **Cross-modal grounding** → invest in locus/saliency plumbing and the overlay UI.
- **Calibrated escalation** → build selective-prediction curves into `eval/`.
- **Verifier consensus** → compute Cohen's κ between specialist and critic in `eval/`.

Recommended for a startup story: **cross-modal grounding** as the visible hook,
with **calibrated escalation** as the trust story underneath. Decide by end of
Phase 3 so Phases 4–7 instrument the right metric. Logged in
[07 — Risks & Decisions](07-risks-decisions.md) as an open decision.
