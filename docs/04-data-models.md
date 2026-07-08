# 04 — Data & Models

> This doc covers *which* datasets and models per vertical. For the concrete
> training recipe — splits, preprocessing, loss functions, metrics, compute budget,
> and promotion gates — see [12 — Training Plan](12-training-plan.md). For how each
> trained model gets wrapped into an agent, see [13 — Agent Build Plan](13-agent-build-plan.md).

## Datasets by vertical

| Vertical | Datasets | Access |
|----------|----------|--------|
| Chest X-ray | **NIH ChestX-ray14**, CheXpert, MIMIC-CXR | NIH/CheXpert open · MIMIC credentialed |
| Brain MRI | **BraTS** (tumor segmentation) | Open (registration) |
| Lung CT | LIDC-IDRI, LUNA16 | Open |
| Histopathology | CAMELYON, PatchCamelyon | Open |
| ECG | **PTB-XL**, MIT-BIH, PhysioNet Challenge sets | PhysioNet DUA |
| Echo | EchoNet-Dynamic | Registration |
| Reports/EHR | MIMIC-III / MIMIC-IV | Credentialed (PhysioNet DUA) |

**Access reality:** several require credentialed access with a PhysioNet Data Use
Agreement (DUA) and CITI training. That paperwork has real lead time — **start it
now, in parallel with MVP**, but do not block the MVP on it. The MVP runs entirely
on fully-open data (NIH ChestX-ray14 + CheXpert for images; a small open guideline
corpus for RAG).

### Data-access plan

1. **Week 0:** register for NIH ChestX-ray14 + CheXpert (open) → unblocks MVP.
2. **Week 0:** begin PhysioNet credentialing (CITI course + DUA) for MIMIC-CXR /
   PTB-XL → ~2–4 week lead time, lands in time for verticals #2–3.
3. **BraTS / LUNA16 / CAMELYON:** register when the corresponding vertical starts.

## Foundation models by vertical

| Vertical | Primary model | Strategy |
|----------|---------------|----------|
| Chest X-ray | **MedGemma 1.5** (VLM) | Zero-shot / light adapt first; CheXpert-CNN as a second opinion for the verifier |
| Brain MRI | **nnU-Net** + MedSAM | Fine-tune nnU-Net on BraTS; MedSAM for prompt-based refinement |
| Lung CT | **CT-FM** embeddings | Use pretrained embeddings + light detection head (avoid full 3D retrain) |
| Histopathology | MedGemma 1.5 / pathology FM | MIL over patches |
| ECG | 1D-CNN / transformer | Train on PTB-XL; MIT-BIH for rhythm |
| Echo | Echo-Vision-FM | Video FM, EF regression |
| Dermatology | MedGemma 1.5 | Zero-shot VLM |

### Model strategy principles

- **Prefer foundation-model embeddings / zero-shot VLM over full retraining**
  wherever the vertical allows. Patch-based or embedding-based approaches keep 3D
  compute costs down (a listed risk) and get a vertical to "demo-able" faster.
- **The verifier needs a genuinely different model** from the specialist. For CXR,
  that means MedGemma (specialist) vs. a CheXpert-trained CNN or a different LLM
  reading the same evidence (critic). Heterogeneity is the whole point — do not let
  both sides be the same backbone.
- **Every finding carries its locus** (voxel region / ECG lead+interval / WSI
  patch) and a saliency reference. This is a hard requirement for cross-modal
  grounding and for the evidence overlays in the dashboard.

## Sourcing models

Pull weights and model cards from Hugging Face (MedGemma, MedSAM, CT-FM, nnU-Net
releases). Track weight references with DVC — **never commit weights or any raw
data to git**. `data/` and `models/` hold pointers only.
