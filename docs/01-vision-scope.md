# 01 — Vision & Scope

## Vision

A clinician drops in *any* medical artifact — a DICOM image, a PDF report, a
12-lead ECG, an EHR excerpt — and Aegis-Dx returns a **draft assessment**: a
ranked differential, each finding tied to visual/signal evidence, each carrying a
calibrated confidence, with low-certainty cases automatically flagged for human
attention. The clinician confirms, edits, or rejects. Confirmed cases feed back
into the system's memory.

The **defensible asset** is the shell, not the models. Foundation models
(MedGemma, MedSAM, CT-FM, nnU-Net) are commoditizing fast; the durable value is
the orchestration, cross-verification, calibration, evidence-grounding, and the
clinician trust surface around them.

## Scope matrix — modality × condition × model class

Each row is an independent vertical you can build one at a time. All plug into the
same shell via the same specialist port.

| Modality | Example conditions | Model class | Foundation model to adapt |
|----------|-------------------|-------------|---------------------------|
| MRI (brain, breast, prostate) | Tumors, lesions, gliomas | 3D segmentation + classification | TotalSegmentator-MRI, MedSAM, nnU-Net |
| CT (chest, abdomen) | Lung nodules/cancer, bleeds | 3D detection + segmentation | CT-FM (148k scans), MedLSAM |
| X-ray (chest) | Pneumonia, effusion, masses | 2D classifier / VLM | MedGemma 1.5, CheXpert-trained CNNs |
| Histopathology | Cancer grading, mitosis | Patch classifier / MIL | MedGemma 1.5, pathology FMs |
| ECG (12-lead signal) | MI (heart attack), arrhythmia | 1D CNN / transformer | PTB-XL / MIT-BIH-trained models |
| Echo / cardiac MRI | Blockage, ejection fraction, wall motion | Video FM | Echo-Vision-FM |
| Dermatology | Skin cancer | 2D VLM | MedGemma 1.5 |
| Free-text reports / EHR | Priors, context | LLM + RAG | Med-LLM + retrieval |

**MedGemma 1.5** (updated Jan 2026) is multimodal across radiology (2D,
longitudinal 2D, 3D), dermatology, histopathology, ophthalmology, and document
understanding — so it can back *several* verticals at once and is the natural
backbone VLM for the early ones. **MedSAM** handles prompt-based (bounding-box)
segmentation generically. **CT-FM** is a 3D foundation model pretrained on 148k+
CT scans.

## MVP boundary (what's in v1)

**In:**
- Chest X-ray image + paired free-text report, end-to-end through all 10 pipeline steps.
- Orchestrator, one imaging specialist, RAG/retrieval, verifier, synthesis, reporter, guardrail.
- Clinician dashboard: image viewer + overlays + confidence + **confirm/edit/reject**.
- De-identification at ingestion; fully-open data only (NIH ChestX-ray14, CheXpert).

**Out (deliberately deferred):**
- 3D verticals (MRI, CT) — heavier compute, steeper pipeline. Vertical #2–3.
- Credentialed datasets (MIMIC, PhysioNet DUAs) — start the paperwork now, don't block MVP on it.
- Retraining/active-learning loop from confirmed cases — logged in MVP, wired later.
- Multi-language reports (Sinhala/Tamil) — a strong later differentiator, not MVP.

## Vertical sequencing

Full scope is all eight modalities. Recommended order (each reuses the shell):

1. **Chest X-ray + report** — fastest, fully-open data, 2D, MedGemma backbone. **← MVP**
2. **Brain MRI (BraTS)** — open data, visually striking masks, first 3D vertical.
3. **ECG (PTB-XL)** — lightweight, proves the signal (non-imaging) path.
4. **Lung CT (LUNA16/LIDC)** — reuses 3D infra from MRI.
5. **Histopathology (CAMELYON)** — patch/MIL, reuses VLM backbone.
6. **Echo (EchoNet-Dynamic)** — video modality.
7. **Dermatology** — 2D VLM, reuses CXR-era infra.
8. **Reports/EHR as a standalone entry point** — RAG-first.

Rationale for the order: maximize shell reuse and open-data availability early;
push 3D-compute and credentialed-data costs later; prove one non-imaging modality
(ECG) mid-sequence to validate the "any artifact" claim.

## Non-goals

- Not a fully autonomous diagnostic device. Human confirmation is the product.
- Not a general medical chatbot. Structured artifact in → structured draft out.
- Not (yet) a regulated SaMD. Research-only framing throughout — see [06](06-compliance-safety.md).
