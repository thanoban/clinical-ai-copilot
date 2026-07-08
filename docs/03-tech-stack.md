# 03 — Tech Stack

## Stack choices

| Layer | Choice |
|-------|--------|
| Orchestration | **LangGraph** (stateful graph) + LangChain; **MCP** for tools |
| Imaging models | PyTorch + **MONAI**, nnU-Net, MedSAM, MedGemma (via HF) |
| Signal | PyTorch (1D CNN / transformer); **NeuroKit2** for ECG preprocessing |
| Medical I/O | **pydicom**, SimpleITK, FHIR/HL7 parsers, Tesseract/OCR |
| RAG | Vector DB (**Qdrant** or **pgvector**) + medical guideline corpus |
| Serving | **FastAPI** backend; Triton / vLLM for model serving |
| Frontend | **Next.js** clinician dashboard (image viewer + overlays) |
| Data/ops | **DVC** for data versioning; MLflow / W&B for experiments |
| Infra | GPU (Vertex AI / on-prem for PHI); containerized |

Your EduFX stack ports directly: **FastAPI + Next.js + hexagonal** is the same
spine. Each specialist becomes an adapter behind a port.

### Platform & cross-cutting layers (what makes it scale + production-grade)

| Layer | Choice |
|-------|--------|
| Async / workflow | Message broker (Redis Streams / RabbitMQ / Kafka) + durable workflow (LangGraph **Postgres checkpointer**; evaluate **Temporal** at scale — D13) |
| Case & audit store | Postgres (case state + event sourcing) + **append-only, hash-chained audit log** |
| Identity | **OIDC / SAML** SSO, SCIM; **RBAC** + per-tenant scoping |
| Secrets | Vault / cloud secrets manager (no secrets in git or images) |
| Observability | **OpenTelemetry** + Prometheus/Grafana + Loki/Tempo (case ID = trace ID) |
| MLOps | Model registry (MLflow) + eval gates + shadow/canary rollout + drift monitoring |
| Delivery to UI | **SSE / WebSocket** (async results) — the dashboard reads case state, not models |
| IaC / deploy | **Terraform** + Helm/Kustomize, GitOps |

Detail: [08 — Scalability](08-scalability-architecture.md),
[09 — Security & Audit](09-security-identity-audit.md),
[10 — Observability & MLOps](10-observability-mlops.md),
[11 — Engineering Practices](11-engineering-practices.md).

## Hexagonal design — the reusability engine

This is what makes "all eight verticals" tractable. The **domain** (orchestration,
verification, calibration, synthesis) never imports a concrete model. It talks to
**ports** (interfaces). Concrete models and I/O live in **adapters**.

### Ports (stable interfaces the domain depends on)

```
IngestionPort        raw bytes + mime → NormalizedArtifact (de-identified)
TriagePort           artifact → {modality, region, urgency}
SpecialistPort       artifact → Finding[]   (masks, detections, saliency, prob, locus)
SignalSpecialistPort signal → Finding[]     (same contract, signal locus)
RetrievalPort        query → EvidenceSnippet[]
VerificationPort     Finding[] → Verification[]  (agreement, κ, flags)
SynthesisPort        (findings, evidence, context) → Differential
ReportPort           Differential → StructuredReport
GuardrailPort        (findings, artifact) → EscalationDecision
FeedbackPort         (report, human_action) → void   (logs, later: retraining)
AuditPort            event → void   (append-only, hash-chained — every consequential action)
IdentityPort         token → Principal{roles, tenant}   (authz + tenant scoping)
```

`AuditPort` and `IdentityPort` are **cross-cutting** — the domain emits audit events
and checks authorization through ports too, so security/audit are testable and
swappable, not hard-wired. See [09 — Security, Identity & Audit](09-security-identity-audit.md).

Every imaging/signal vertical implements the **same `SpecialistPort`**. Adding
vertical #2 = write one new adapter + register it with the triage router. The
orchestrator graph does not change. That property is the MVP's acceptance test for
the shell.

The current walking skeleton now follows this shape directly: workflow analysis
resolves a specialist by triaged modality through a registry, rather than embedding
modality-specific logic in the workflow itself. Retrieval, synthesis, and report
generation are also now wired behind their own ports with stub adapters, so the
workflow owns sequencing while adapters own content generation.

### Adapters (swappable implementations)

```
adapters/
  ingestion/    dicom_adapter.py   pdf_ocr_adapter.py   fhir_adapter.py
  specialists/  cxr_medgemma_adapter.py   brain_nnunet_adapter.py
                lung_ctfm_adapter.py      path_mil_adapter.py
  signal/       ecg_cnn_adapter.py        echo_visionfm_adapter.py
  retrieval/    qdrant_adapter.py
  verification/ heterogeneous_llm_adapter.py
  llm/          gemini_adapter.py   claude_adapter.py   (orchestrator + synth + report)
  calibration/  temperature_scaling.py    ood_mahalanobis.py
```

## Proposed repo layout

```
aegis-dx/
  README.md
  docs/                     ← this planning set
  apps/
    api/                    FastAPI — thin HTTP layer; async intake (202 + case id)
    web/                    Next.js clinician dashboard (SSE/WebSocket results)
    orchestrator/           durable workflow runner (LangGraph + Postgres checkpointer)
    workers/                specialist + de-id workers (consume queues, call model servers)
  packages/
    core/                   domain: ports, entities, the LangGraph graph
      graph/                nodes + conditional edges (the 4–5 verify loop)
      ports/                the interfaces above
      entities/            Finding, Differential, Verification, StructuredReport…
    adapters/               concrete implementations (see above)
    shared/                 types, config, logging, telemetry, PHI utils, audit + identity clients
  models/                   model cards, weights refs (DVC-tracked, not in git)
  data/                     DVC pointers only — never raw PHI in git
  eval/                     benchmark harness, ablation scripts, κ, calibration, subgroup gates
  infra/                    Terraform, Helm/Kustomize, Dockerfiles, CI/CD pipelines
  observability/            OTel collector config, Grafana dashboards, alert (SLO) rules
```

## Serving notes

- Specialists run **in parallel on independently-scaled worker pools** (autoscaled
  on queue depth), *not* inside the request. Heavy 3D models get their own GPU-backed
  inference service (Triton/vLLM/KServe) with dynamic batching; the adapter is a thin
  client. The durable workflow engine dispatches jobs and gathers results via
  checkpointing, so a crash resumes rather than restarts — see
  [08 — Scalability & Production Architecture](08-scalability-architecture.md).
- LLM calls (orchestrator, verifier, synthesis, reporter) go through the `llm/`
  adapters so the *heterogeneous verifier* rule is enforced by config: the verifier
  adapter must be a different provider/model than the synthesis adapter. (Use the
  `claude-api` reference for current Claude model IDs when wiring the Claude adapter.)
- All PHI-touching services run in a PHI-safe environment (on-prem or a locked-down
  VPC); de-identification happens in the **IngestionPort** adapter, before anything
  else sees the artifact.
- **Only de-identified data leaves the PHI boundary.** External LLM calls
  (orchestrator/verifier/synthesis/reporter) route through a single controlled **LLM
  gateway** egress point — or use in-VPC / BAA-covered / self-hosted models (D11).
  The gateway also does caching, retries, cost tracking, and enforces the
  heterogeneous-verifier rule. See [09 — Security, Identity & Audit](09-security-identity-audit.md).
