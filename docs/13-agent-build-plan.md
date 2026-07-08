# 13 — Agent Build Plan

[02 — Architecture](02-architecture.md) defines *what* each agent does. This doc is
the **build order and acceptance criteria** for actually implementing them: which
port each agent satisfies ([03](03-tech-stack.md)), its concrete I/O contract, the
prompt/model strategy for LLM-backed agents, and the contract test
([11](11-engineering-practices.md)) that proves it's done. Build in this order —
each agent unblocks the next.

## Build order (maps to [05 — Roadmap](05-roadmap.md) phases)

```
Phase 0–1:  Ingestion → Triage                         (data in, classified)
Phase 2:    Imaging specialist (CXR)                   (first real finding)
Phase 3:    Orchestrator → Knowledge/RAG → Report/EHR → Synthesis → Reporter
Phase 4:    Verifier/critic → Guardrail                (trust layer)
Phase 5:    (dashboard consumes all of the above — not an agent, see 08/09)
Phase 6+:   Additional imaging/signal specialists reuse this same recipe
```

Rationale: you cannot test an orchestrator with nothing to route to, and you cannot
test a verifier with nothing to verify. Build bottom-up (ingestion → one specialist
→ orchestration → trust layer), not top-down.

---

## 1. Ingestion agent

**Port:** `IngestionPort` — `raw bytes + mime → NormalizedArtifact (de-identified)`

**Build steps:**
1. Format detection (DICOM / PDF / signal file / FHIR bundle) by magic bytes + mime, not filename.
2. Per-format parser: `pydicom` (DICOM tags + pixel array), OCR via Tesseract (scanned PDF reports), a plain-text/FHIR path for structured EHR excerpts.
3. **De-identification pass** — strip DICOM PHI tags (patient name, ID, birthdate, institution, accession numbers per the DICOM PS3.15 de-id profile), OCR-detected free-text identifiers (regex + NER for names/dates/MRNs in report text/burned-in image text).
4. Normalize: consistent internal artifact schema regardless of source format (`modality_hint`, `pixel_data | signal_data | text`, `provenance`).
5. Emit an `AuditPort` event for every ingestion (who submitted, de-id pass/fail) — see [09](09-security-identity-audit.md).

**Acceptance / contract test:**
- Given a sample DICOM with known PHI tags → output contains **zero** of those tags (automated PHI-leak check, not manual review, per the safety checklist in [06](06-compliance-safety.md)).
- Given each supported format → produces a valid `NormalizedArtifact` matching the shared schema.
- Malformed/corrupt input → clean rejection with a typed error, never a silent pass-through.

**No LLM in this agent** — deterministic parsing + a de-id model/ruleset, chosen for auditability (you can prove *why* something was or wasn't redacted).

---

## 2. Triage agent

**Port:** `TriagePort` — `artifact → {modality, region, urgency}`

**Build steps:**
1. Lightweight classifier (small CNN/rules) for modality detection from DICOM metadata (`Modality` tag) when present — fast path, no model call needed.
2. Fallback VLM classification (MedGemma) when metadata is missing/unreliable — image → modality + body region.
3. Urgency heuristic: rule-based initially (e.g., certain DICOM priority flags, keyword flags in an accompanying report like "STAT"), refined later with a learned urgency model once labeled data exists.
4. Route decision: map `{modality, region}` → which `SpecialistPort` adapter(s) to invoke (this routing table is config, not code — adding vertical #2 means adding a config row, not a triage rewrite).

**Acceptance / contract test:**
- Metadata-present case → correct modality without a model call (cheap path exercised).
- Metadata-absent case → VLM fallback produces a modality label with a confidence score.
- Unknown/unsupported modality → routes to `Degraded`/manual-review, never guesses a specialist.

---

## 3. Imaging specialist (first instance: chest X-ray)

**Port:** `SpecialistPort` — `artifact → Finding[]` (masks, detections, saliency, probability, locus)

Every subsequent vertical (MRI, CT, path, derm) implements this **same port** — this
is the template to copy.

**Build steps:**
1. Wrap the trained/adapted model ([12 — Training Plan](12-training-plan.md), Vertical 1) behind a thin inference client — the adapter, not the model itself, is what the domain calls.
2. Map raw model output → `Finding[]` shape: `{claim, locus, probability, source_agent, model_version, saliency_ref}`. This mapping step is where model-specific messiness (label indices, box formats) gets normalized away from the domain.
3. Attach saliency (Grad-CAM / attention map) as `saliency_ref` — required for the cross-modal-grounding novelty ([05](05-roadmap.md)).
4. Wire timeouts/retries/circuit-breaker ([08](08-scalability-architecture.md)) around the model-server call.
5. Register the model in the **model registry** in `shadow` status before it's callable in any real pipeline run ([10](10-observability-mlops.md)).

**Acceptance / contract test (the shared `SpecialistPort` contract suite — [D14](07-risks-decisions.md)):**
- Given a fixed test artifact → returns a well-formed `Finding[]` (schema-valid, every finding has a non-null `locus` and `probability` in [0,1]).
- Timeout/failure injection → the adapter surfaces a typed failure, the graph moves the case to `Degraded`, no exception escapes to crash the orchestrator.
- **This exact suite, unmodified, is what every future vertical's specialist adapter must also pass** — that's the mechanical proof the shell doesn't need orchestrator changes per vertical.

---

## 4. Knowledge/RAG agent

**Port:** `RetrievalPort` — `query → EvidenceSnippet[]`

**Build steps:**
1. Ingest an initial open guideline corpus (radiology reporting guidelines, relevant clinical practice guidelines for the CXR vertical) into the vector DB (Qdrant/pgvector, [03](03-tech-stack.md)).
2. Embedding model choice (a medical-domain embedding model if available; a strong general embedding model otherwise) — document the choice as a small ADR if revisited later.
3. Retrieval query construction from the case state (`modality`, `findings[]` so far, `region`) — not just the raw artifact.
4. Return `EvidenceSnippet[]` with source citation (document + section) so the reporter agent can produce evidence-linked output, matching the product's evidence-traceability promise.

**Acceptance / contract test:**
- Query for a known finding → retrieves the expected guideline snippet in the top-k (a small golden retrieval set, not vibes-based checking).
- Empty/no-match corpus case → returns empty, not a hallucinated snippet.

---

## 5. Report/EHR agent

**Port:** implements the LLM+RAG "clinical context" role feeding the orchestrator's state — reads free-text reports/EHR excerpts already normalized by Ingestion.

**Build steps:**
1. LLM extraction prompt (structured output — JSON schema, not free text) pulling: prior conditions, current symptoms, medications, prior imaging mentions.
2. Strict output schema validation — reject and retry on malformed JSON rather than passing bad data downstream (the "strict formatting rules to mitigate hallucination" principle from [02](02-architecture.md)).
3. Cross-reference extracted priors against `RetrievalPort` for relevant guideline context (e.g., a documented prior MI changes which guidelines are relevant).

**Acceptance / contract test:**
- Given a synthetic report with known facts embedded → extraction recovers those facts with schema-valid output.
- Given a report with no relevant priors → returns an explicitly empty/null structure, not fabricated context.

---

## 6. Orchestrator agent

**Not a port itself** — it *is* the LangGraph graph that wires every port together, defined in `packages/core/graph/` ([03](03-tech-stack.md)).

**Build steps:**
1. Define the graph nodes = one node per agent above, edges = the pipeline order ([02](02-architecture.md)).
2. Implement the **conditional edge** for the verify loop (step 4↔5): on verifier conflict, route back to re-query rather than proceeding — this is the one truly novel piece of graph logic, build and test it in isolation first with fake findings before wiring real specialists.
3. State schema = the shape defined in [02 — State shape](02-architecture.md), versioned as a shared type.
4. Durable checkpointing via the Postgres checkpointer ([08](08-scalability-architecture.md), [D9](07-risks-decisions.md)) — a crash mid-graph resumes, doesn't restart.
5. Emit `case_id`-correlated telemetry (trace span per node) from the start — retrofitting tracing later is exactly the anti-pattern [08](08-scalability-architecture.md) warns against.

**Acceptance / contract test:**
- Integration test: graph wired with **fake, deterministic adapters** for every port → exercises the full pipeline, the verify-loop conditional edge (force a manufactured conflict), and the `Degraded` path (force a manufactured specialist failure) — all without a single GPU or LLM call ([11](11-engineering-practices.md)).
- Crash-mid-graph test: kill the orchestrator process mid-case → restart → case resumes from last checkpoint, not from `Received`.

---

## 7. Verifier/critic agent

**Port:** `VerificationPort` — `Finding[] → Verification[]` (agreement, κ, flags)

**Build steps:**
1. Select a genuinely **different** model/provider from whatever backs the specialist and synthesis agents ([D6](07-risks-decisions.md)) — enforce this at config level, not just convention (fail startup if verifier model == synthesis model).
2. Critic prompt: given a finding + the artifact/evidence, argue *for* and *against* the claim, output a structured agreement score + flags — not a free-text opinion.
3. Implement **calibration-gated intensity** ([D15](07-risks-decisions.md)): a lightweight single-pass check for high-confidence/in-distribution findings, the full adversarial critique + re-query loop for low-confidence/OOD/high-stakes findings.
4. Compute **Cohen's κ** between specialist and critic across a labeled eval set — this is both a novelty metric ([05](05-roadmap.md)) and a live production signal ([10](10-observability-mlops.md)).

**Acceptance / contract test:**
- Given a finding known to be correct (from a labeled eval case) → critic agrees.
- Given a finding known to be a hallucination (adversarially constructed test case) → critic flags it and disagreement routes back to the orchestrator's re-query edge.
- Startup check: verifier and synthesis configs must resolve to different model identities, or the service refuses to start.

---

## 8. Synthesis agent

**Port:** `SynthesisPort` — `(findings, evidence, context) → Differential`

**Build steps:**
1. Fusion prompt: given verified findings + retrieved evidence + clinical context (from Report/EHR agent), produce a ranked differential with a fused confidence per item.
2. Confidence fusion logic should combine specialist probability + verifier agreement score, not just pass through the specialist's raw number — this is where "cross-verification actually changes the output" becomes real rather than cosmetic.
3. Every item in the differential retains links back to its source `Finding[]` (locus/saliency) — required for evidence-linked reporting.

**Acceptance / contract test:**
- Given conflicting findings from two specialists (manufactured test case) → the differential reflects appropriately reduced confidence, not a naive average that hides the conflict.
- Every differential item traces back to at least one `Finding` — no orphaned conclusions.

---

## 9. Guardrail agent

**Port:** `GuardrailPort` — `(findings, artifact) → EscalationDecision`

**Build steps:**
1. Confidence-threshold check against per-vertical, **per-site** calibrated thresholds ([D16](07-risks-decisions.md)) — not a single global cutoff.
2. OOD detector (start simple — e.g., Mahalanobis distance on embeddings vs. training distribution; iterate as real site data arrives).
3. Escalation decision is a hard boolean + reason, feeding the case state machine's `Escalated` transition ([08](08-scalability-architecture.md)).
4. **Never suppress an escalation to look more capable** — this is a policy encoded as a test, not just a principle in prose ([06](06-compliance-safety.md)).

**Acceptance / contract test:**
- Below-threshold confidence case → escalates, always, regardless of any other agent's output.
- Synthetic OOD input (wrong modality-for-vertical, corrupted image) → escalates via the OOD path, not silently scored.

---

## 10. Reporter agent

**Port:** `ReportPort` — `Differential → StructuredReport`

**Build steps:**
1. Templating (not free-generation) for the report skeleton — sections, disclaimers, evidence links — with an LLM filling narrative connective text only within that fixed structure. This is the "strict formatting rules" principle applied at the last mile, where it matters most because this is what the clinician actually reads.
2. **Research-only disclaimer is a template field, not optional prose** — cannot be omitted by a prompt drifting off-script ([06](06-compliance-safety.md)).
3. Every finding/differential item in the report links to its evidence (guideline snippet) and its locus/saliency overlay reference, feeding the dashboard.

**Acceptance / contract test:**
- Output is schema-valid structured data (not raw LLM text) that the dashboard can render deterministically.
- Disclaimer field is present and non-empty in 100% of generated reports (a literal assertion in the test, not a spot check).

---

## Cross-cutting: what "done" means for any agent

Borrowing the Definition of Done from [11](11-engineering-practices.md), an agent is
buildable-complete when:

- [ ] It implements its port's shared contract test suite (green).
- [ ] It emits `case_id`-correlated traces and, where it takes a consequential
      action, an audit event ([09](09-security-identity-audit.md)).
- [ ] If LLM-backed: output is schema-validated, not free text passed downstream.
- [ ] If model-backed: the model is registry-tracked with an eval report
      ([10](10-observability-mlops.md), [12](12-training-plan.md)).
- [ ] Failure modes (timeout, malformed output, low confidence) have an explicit,
      tested path — never a silent pass-through or a crash.
