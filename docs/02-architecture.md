# 02 — Architecture

## Why multi-agent (not architecture for its own sake)

The literature shows measurable, not cosmetic, gains from the multi-agent pattern
in clinical decision-making:

- Multi-agent oncology decision-making accuracy improved from **30.3% → 87.2%**.
- Reached **93.2%** on USMLE-style benchmarks via simulated clinical evolution.
- Built with LangGraph, CrewAI, and the Model Context Protocol (MCP) so specialized
  agent teams divide labor, use precision tools, and **cross-verify** outputs.

The winning pattern is an **orchestrator architecture**: a central agent
dynamically routes queries to specialized tools, with strict output formatting to
mitigate hallucination.

**The single most important design choice** is that the *verifier ≠ the specialist
model*. Medical MLLM hallucination is a documented, benchmarked failure mode.
Consensus/critique between **heterogeneous** models is the primary defense — this
is a hard architectural rule, not a nice-to-have.

### Prior art to position against (and cite)

MDAgents, ColaCare, MDTeamGPT, Agent Hospital, Tree-of-Reasoning, ClinicalAgents
(dual-memory).

## Agent roster (the LangGraph nodes)

| Agent | Job | Backing model / tool | Output |
|-------|-----|----------------------|--------|
| **Orchestrator** | Classify input, route to specialists, control the loop | LLM (Gemini 2.5 / Claude) | Routing plan, state |
| **Ingestion** | Parse DICOM/PDF/signal, de-identify, normalize | pydicom, OCR, HL7/FHIR | Structured artifact |
| **Triage** | Detect modality + body region + urgency | Lightweight classifier + VLM | Modality label, priority |
| **Imaging specialists** (1/vertical) | Segment + detect + classify | nnU-Net / MedSAM / CT-FM / MedGemma | Findings + masks + heatmaps |
| **Signal specialist** | ECG/echo analysis | 1D-CNN / Echo-Vision-FM | Rhythm, MI probability, EF |
| **Report/EHR** | Extract priors, symptoms, meds | LLM + RAG over notes | Clinical context |
| **Knowledge/RAG** | Pull guidelines, similar prior cases | Vector DB + retriever | Evidence snippets |
| **Verifier/critic** | Challenge specialist claims, check consistency | A *second, different* LLM | Agreement score, flags |
| **Synthesis** | Fuse findings → differential + confidence | LLM | Draft assessment |
| **Reporter** | Structured report, evidence links, disclaimers | LLM + templating | Human-facing report |
| **Guardrail** | Uncertainty, OOD, refusal | Calibration + OOD detector | Escalate-to-human trigger |

## Pipeline — top to bottom

> This is the **logical** flow. At runtime it is an *asynchronous, durable,
> event-driven workflow* — a case is a checkpointed state machine over a message
> broker and independently-scaled worker pools, not a blocking call. See
> [08 — Scalability & Production Architecture](08-scalability-architecture.md) for
> the runtime view, the tiers, and the case state machine.

```
1. INGEST      DICOM / PDF / signal / EHR → de-identify (PHI stripped) → normalize
2. TRIAGE      modality + region + urgency detected → route
3. RETRIEVE    RAG: prior scans, patient history, clinical guidelines
4. ANALYZE     relevant imaging/signal specialists run in PARALLEL
                 → segmentation masks, detections, saliency maps, probabilities
5. VERIFY      critic agent + second model challenge each finding
                 → consensus? conflict? confidence per finding
6. SYNTHESIZE  fuse image + signal + text + priors → ranked differential
7. CALIBRATE   guardrail: confidence + OOD check → auto-escalate low-certainty
8. REPORT      structured draft: findings, evidence overlays, confidence, next steps
9. DELIVER     clinician dashboard → human confirms/edits → feedback logged
10. LEARN      confirmed cases feed retraining / RAG memory
```

**Steps 4–5 are the LangGraph-managed loop:** if the verifier disagrees with a
specialist, the orchestrator can re-query (different prompt, different model, or
request additional evidence) before proceeding. This conditional edge is the heart
of the graph.

Every node runs with **timeouts, retries, and a circuit breaker**. If a specialist
exhausts its retries the case moves to a **`Degraded`** state and reaches the
clinician with an explicit "analysis unavailable" gap rather than a fabricated
finding. Verification intensity is **calibration-gated** — full heterogeneous
critique fires on low-confidence / OOD / high-stakes findings, a lightweight check
otherwise, which controls both LLM cost and latency. Both behaviours are detailed in
[08 — Scalability & Production Architecture](08-scalability-architecture.md).

**Step 9 is non-negotiable:** nothing becomes clinically actionable until a human
confirms. The dashboard's confirm/edit/reject action is a required gate, not a
convenience.

## State shape (LangGraph)

The graph state carries, at minimum:
- `case_id`, `tenant_id`, `status` — correlation ID (traced through every agent),
  multi-tenant scoping, and position in the state machine ([08](08-scalability-architecture.md)).
- `artifact` — normalized, de-identified input + provenance.
- `modality`, `region`, `urgency` — from triage.
- `evidence[]` — retrieved snippets, prior cases.
- `findings[]` — each: `{claim, locus (voxel/lead/patch), probability, source_agent, model_version, saliency_ref}`.
- `verification[]` — per-finding agreement score, critic flags, κ where applicable.
- `differential[]` — ranked, with fused confidence.
- `escalation` — bool + reason (low confidence / OOD / verifier conflict).
- `report` — structured draft.
- `human_action` — confirm / edit / reject + edits (populated at step 9).

Keeping *locus* on every finding is what makes cross-modal grounding (novelty #1)
possible — a finding always knows which pixels/leads/patches produced it.
