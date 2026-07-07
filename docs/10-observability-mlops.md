# 10 — Observability & MLOps

A multi-agent system is a distributed system: when a draft is wrong, "which of the
nine agents caused it, on which case, with which model version?" must be answerable
in minutes. And because the core asset is *models*, their lifecycle needs the same
rigor as code. Both are foundational tracks, present from Phase 1 — not a Phase-7
add-on.

## Observability

### Correlation — one case, one thread

The **case ID is the correlation ID**, propagated as OpenTelemetry trace/baggage
through the gateway, the workflow engine, every worker, every model server, and every
LLM call. A single trace shows the full multi-agent flow for a case — this is the
difference between "debuggable" and "unexplainable."

### The three signals

- **Traces (OpenTelemetry).** Span per agent/node; nested spans for model-server and
  LLM calls. Answers "what happened to case X and where did the time go."
- **Metrics (Prometheus + Grafana).** The ones that matter here:
  - Per-agent / per-node latency (p50/p95/p99).
  - Queue depth per specialist (drives autoscaling *and* alerting).
  - GPU utilization + batch efficiency per model server.
  - **LLM token spend and cost per case** (startup runway signal).
  - **Escalation rate** and **verifier-disagreement rate** (model-health signals).
  - **Confirm / edit / reject rates by model version** — the real-world ground-truth
    proxy. A rising reject rate on a new model version is your earliest quality alarm.
- **Logs.** Structured JSON, **PHI-scrubbed**, correlated by case ID. Logs are for
  detail; traces/metrics are for shape.

### Alerting (SLO-driven)

Alert on **SLO burn**, not raw thresholds: latency-SLO burn, queue backlog growth,
escalation-rate spike, verifier-disagreement spike, cost-per-case spike, drift
detector firing (below). Every alert links to the trace/dashboard for the offending
cases.

## MLOps — model lifecycle

The specialists and calibrators are the product's crown jewels. Treat them like
released software.

### Model registry

Every model version is registered with: provenance (data + code + config hash),
**model card**, eval results (including per-subgroup), and an **approval status**
(shadow → canary → production → deprecated). Nothing serves production traffic
without a registry entry and an approval. Weights are DVC/registry-tracked, never in
git ([03](03-tech-stack.md)).

### Eval as a CI gate

A PR that changes a model, a prompt, or a calibrator **runs the eval suite in CI**
and is **blocked on regression** — especially a **per-subgroup** regression
([06](06-compliance-safety.md)). "It's better on average" is not acceptable if it's
worse for a subgroup. This is where the `eval/` harness (κ, calibration curves,
selective-prediction) becomes a gate, not just a report.

### Progressive rollout

1. **Shadow.** New model runs alongside the current one on live cases, its output
   **logged and compared but never shown** to clinicians. Zero patient risk.
2. **Canary.** After shadow looks good, serve a small % of traffic (per-tenant),
   watch confirm/reject and escalation deltas.
3. **Promote or roll back.** Registry pin + fast redeploy makes rollback a
   config change, not a rebuild.

### Drift & performance monitoring

- **Input drift:** scanner/manufacturer mix, demographics, image-quality stats
  shifting away from training distribution → OOD detector + drift alert.
- **Performance proxy:** confirm/edit/reject rates by model version and by site.
  Because ground truth (the clinician's decision) arrives at step 9, you get a
  continuous, real-world quality signal for free — wire it into drift alerting.
- **Per-site** monitoring, since calibration is per-site ([08](08-scalability-architecture.md)).

### The feedback → retraining loop (the Phase-10 "LEARN" step, done safely)

Confirmed/edited cases feed a **labeling + retraining pipeline** with full data
lineage. Retraining is **triggered and reviewed**, never automatic-to-production —
a new model still goes shadow → canary → promote. This closes the loop from
[02](02-architecture.md) step 10 without letting the system silently retrain itself
into a corner.

## Tooling summary

| Concern | Tool (initial) |
|---------|----------------|
| Tracing | OpenTelemetry → Tempo/Jaeger |
| Metrics | Prometheus + Grafana |
| Logs | Structured JSON → Loki/ELK (PHI-scrubbed) |
| Experiments | MLflow / W&B |
| Model registry | MLflow Registry (or equivalent) |
| Data/version | DVC |
| Alerting | Grafana Alerting / Alertmanager, SLO-based |
