# 12 — Training Plan

This doc turns [04 — Data & Models](04-data-models.md) from "which dataset" into
"how we actually train, evaluate, and promote each model." It is organized per
vertical, in the sequencing order from [01](01-vision-scope.md), and follows the
model-lifecycle rules in [10 — Observability & MLOps](10-observability-mlops.md)
(registry, eval-as-CI-gate, shadow → canary → promote). Nothing here trains a model
that skips that lifecycle.

## Cross-cutting training principles (apply to every vertical)

1. **Patient-level splits, always.** Split by `patient_id`, never by image/study. A
   patient with multiple studies must land entirely in train, val, *or* test — never
   split across them. This is the single most common medical-ML leakage bug (NIH
   ChestX-ray14 and CheXpert both have repeat patients).
2. **Known cross-dataset overlap.** MIMIC-CXR, CheXpert, and NIH ChestX-ray14 share
   patients/institutions in places. When combining datasets, dedupe by patient
   metadata before splitting, or keep datasets in separate train/test roles (e.g.,
   train on CheXpert, hold out NIH entirely as an external test set).
3. **Fixed split, versioned.** Splits are generated once, hashed, and stored in
   `data/splits/<dataset>.json` under DVC. Re-running training must reproduce the
   exact same split — no re-randomizing between runs.
4. **Class imbalance is the default state**, not the exception (e.g., "no finding"
   dominates CXR; tumor voxels are a small fraction of an MRI volume). Handle with
   weighted loss / focal loss / oversampling — decided per vertical below, not
   generically "fixed."
5. **Every training run is logged to MLflow/W&B**: config hash, data-split hash,
   git commit, seed, resulting checkpoint, and full eval report (including
   subgroups). No checkpoint enters the model registry ([10](10-observability-mlops.md))
   without this trail.
6. **Post-hoc calibration is a separate, mandatory training step** — never assume a
   model's raw softmax/sigmoid is a calibrated probability. Temperature scaling (or
   isotonic regression) is fit on a held-out calibration split, per model, and
   **per site** once real site data exists ([08](08-scalability-architecture.md), D16).
7. **Subgroup evaluation is mandatory, not optional**, before any promotion: age
   band, sex, and — where metadata exists — scanner/manufacturer and site. A model
   that improves on average but regresses on a subgroup **fails the eval gate**
   ([10](10-observability-mlops.md), [06](06-compliance-safety.md)).
8. **Prefer adapting a foundation model over training from scratch.** Full retrains
   are the exception, reserved for the 1D ECG model where a strong open foundation
   model doesn't yet dominate the space.

## Vertical 1 — Chest X-ray (MVP)

**Datasets:** NIH ChestX-ray14 (~112k images, 14 labels, open), CheXpert (~224k
images, open with registration), MIMIC-CXR (~377k images, credentialed — later).
*(Counts are approximate; confirm current numbers at registration — datasets get
revised.)*

**Task:** multi-label classification (14 CheXpert/NIH pathology labels) +
free-text report grounding, feeding the `SpecialistPort` contract
([03](03-tech-stack.md)): `Finding[]` with `{claim, locus, probability}`.

**Strategy — adapt, don't retrain from scratch:**
- **Zero-shot / few-shot first pass** with **MedGemma 1.5** as the VLM specialist —
  get the pipeline (steps 1–9) working end-to-end before any fine-tuning.
- **Second opinion / verifier signal:** fine-tune a **CheXpert-pretrained CNN**
  (DenseNet121 baseline is the standard, well-documented starting point) as a
  *heterogeneous* second model — this is what the verifier ([D6](07-risks-decisions.md))
  actually compares against, so it must be trained independently of MedGemma.
- **Locus/grounding:** use Grad-CAM/saliency from the CNN and/or MedGemma's
  attention/box output as the `saliency_ref` — needed for cross-modal grounding
  (novelty candidate, [05](05-roadmap.md)).

**Split:** 80/10/10 train/val/test, patient-level, stratified by label prevalence
(rare findings like "pneumothorax" need guaranteed presence in val/test).

**Preprocessing:** resize/pad to model's native resolution, min-max or
CLAHE-normalized intensity, DICOM→PNG conversion at ingestion (not stored raw in
training pipeline — pulled through `IngestionPort` semantics even in offline training).

**Loss / imbalance:** weighted binary cross-entropy per label (inverse label
frequency), or focal loss if weighting alone under-performs on rare labels.

**Metrics:** per-label AUROC (the CheXpert-standard reporting metric), plus
precision/recall at the escalation threshold used by the guardrail
([08](08-scalability-architecture.md)). Report per-subgroup AUROC (age, sex).

**Compute:** single-GPU fine-tune for the CNN (hours, not days); MedGemma used via
inference API/local serving, no full fine-tune needed for MVP.

**Promotion gate:** CNN checkpoint must beat a trivial baseline (prevalence-weighted
prior) on every label and show no subgroup AUROC regression > a set tolerance
(define the tolerance in `eval/` config, e.g. 2 points) before registry promotion.

## Vertical 2 — Brain MRI (BraTS)

**Dataset:** BraTS (multi-modal MRI: T1, T1ce, T2, FLAIR; tumor sub-region
segmentation masks), open with registration.

**Task:** 3D segmentation (whole tumor / tumor core / enhancing tumor), feeding
`Finding[]` with a **voxel-region locus**.

**Strategy:** fine-tune **nnU-Net** (its self-configuring pipeline handles most
preprocessing/architecture decisions automatically — do not hand-roll a 3D U-Net
from scratch) on BraTS; use **MedSAM** for interactive/prompt-based refinement in
the dashboard (a clinician can nudge a boundary, which re-prompts MedSAM rather
than re-running the full segmentation).

**Split:** patient-level 80/10/10 (BraTS ships an official train/val split — use it
as the base, carve the additional test split from train if needed, never touch
BraTS's own validation leaderboard data as training data).

**Preprocessing:** nnU-Net's built-in pipeline (resampling to common spacing,
z-score intensity normalization per modality, skull-stripping if not pre-applied).

**Loss:** Dice + cross-entropy compound loss (nnU-Net default) — proven for
class-imbalanced 3D segmentation where tumor voxels are a small fraction of the volume.

**Metrics:** Dice score and Hausdorff distance per tumor sub-region (the BraTS-
standard metrics) — report per sub-region, not just an average.

**Compute:** the known cost driver in [07 — Risks](07-risks-decisions.md) ("3D
compute cost"). Mitigate with nnU-Net's patch-based training (not full-volume) and
mixed precision; budget a multi-GPU node or cloud GPU burst for this vertical
specifically, not the always-on CXR budget.

**Promotion gate:** Dice ≥ published nnU-Net BraTS baseline (use the original
nnU-Net BraTS paper numbers as the bar) before shadow deployment.

## Vertical 3 — ECG (PTB-XL)

**Datasets:** PTB-XL (~21.8k 12-lead ECGs, ~18.9k patients, 10s recordings,
PhysioNet DUA), MIT-BIH (48 half-hour annotated recordings, rhythm-focused).

**Task:** 1D multi-label classification (PTB-XL's SCP-ECG statement hierarchy:
normal / MI / STTC / conduction disturbance / hypertrophy) feeding `Finding[]`
with a **lead + time-interval locus**.

**Strategy — the one vertical trained closer to scratch:** no dominant open
foundation model for 12-lead ECG yet, so train a **1D-CNN or CNN+transformer
hybrid** directly on PTB-XL. Use **NeuroKit2** ([03](03-tech-stack.md)) for R-peak
detection and beat segmentation as engineered features alongside the raw-signal
model — a well-documented combination in the PTB-XL benchmarking literature.

**Split:** PTB-XL ships **official stratified folds** (10-fold, patient-disjoint) —
**use them as-is**; do not re-split. This also makes results directly comparable to
published PTB-XL benchmarks.

**Preprocessing:** resample to a fixed rate (100Hz or 500Hz, matching PTB-XL's two
released sampling rates — pick one and be consistent), baseline-wander removal,
per-lead z-normalization.

**Loss:** weighted multi-label BCE (SCP-ECG statements are multi-label and
imbalanced — MI-related labels are rarer than "normal").

**Metrics:** macro-AUROC across SCP-ECG superclasses (the PTB-XL-standard
reporting metric), plus sensitivity for the clinically critical classes (MI,
life-threatening arrhythmias) — a missed MI is a different risk tier than a missed
minor conduction abnormality, so track it separately from the aggregate score.

**Compute:** cheapest vertical — single GPU, hours. Good candidate to also
prototype the **calibration + OOD pipeline** ([08](08-scalability-architecture.md))
before it's needed on heavier verticals.

## Verticals 4–7 (Lung CT, Histopathology, Echo, Dermatology)

Full recipes are written **when each vertical's phase starts** ([05 — Roadmap](05-roadmap.md),
Phase 6+), following the same template as above (dataset → split discipline →
preprocessing → loss/imbalance → metrics → compute → promotion gate). Placeholder
strategy per [04](04-data-models.md):

| Vertical | Strategy sketch |
|----------|-----------------|
| Lung CT | **CT-FM embeddings + lightweight detection head** — avoid full 3D retrain (same compute-cost mitigation as BraTS, but embedding-based here since CT-FM is pretrained for exactly this). |
| Histopathology | **MIL (multiple-instance learning) over patches** from CAMELYON WSIs — patch-level foundation-model embeddings (MedGemma or a pathology FM) + a slide-level aggregator, not a from-scratch CNN over gigapixel images. |
| Echo | **Echo-Vision-FM** fine-tuned for ejection-fraction regression + wall-motion classification on EchoNet-Dynamic. |
| Dermatology | **MedGemma 1.5 zero-shot**, same pattern as CXR's first pass — evaluate before committing to any fine-tune. |

## Data-access plan (training-specific additions to [04](04-data-models.md))

| Milestone | Action | Lead time |
|-----------|--------|-----------|
| Week 0 | Register NIH ChestX-ray14 + CheXpert (open) | Immediate — unblocks Vertical 1 |
| Week 0 | Begin PhysioNet CITI training + DUA (MIMIC-CXR, PTB-XL, MIT-BIH) | 2–4 weeks — lands before Vertical 3 |
| Vertical 2 start | Register BraTS | Days |
| Vertical 4 start | Register LIDC-IDRI/LUNA16 | Days |
| Vertical 5 start | Register CAMELYON | Days |
| Vertical 6 start | Register EchoNet-Dynamic | Days |

## Training infrastructure

- **Experiment tracking:** MLflow/W&B for every run ([03](03-tech-stack.md),
  [10](10-observability-mlops.md)) — no untracked training.
- **Data versioning:** DVC for datasets, splits, and preprocessing artifacts.
- **Reproducibility:** pinned environment (container image per training job),
  fixed seeds, config-as-code (not notebook-only training).
- **From checkpoint to production:** every trained checkpoint enters the **model
  registry** in `shadow` status. It only reaches `production` after the eval gate
  passes and a canary period completes ([10](10-observability-mlops.md)). Training
  a model is necessary but never sufficient for deployment.
