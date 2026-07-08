# 04 — Data & Models

> This doc covers *which* datasets and models per vertical, with **verified links**
> (checked against the Hugging Face Hub — see the note on verification below). For
> the concrete training recipe — splits, preprocessing, loss functions, metrics,
> compute budget, and promotion gates — see [12 — Training Plan](12-training-plan.md).
> For how each trained/adapted model gets wrapped into an agent, see
> [13 — Agent Build Plan](13-agent-build-plan.md).

## Principle: use a trained model before training one

If a real, working checkpoint already exists (on Hugging Face or another
reputable source) that fits a `SpecialistPort`/`VerificationPort` role, **adapt or
call it** instead of training from scratch — this is faster to a demo, cheaper, and
lower-risk. Training from scratch is reserved for verticals where nothing suitable
exists (below: **ECG** is the clearest case). Every link below was checked on the
Hub at planning time — **re-verify the repo card, license, and last-updated date
before pulling into the pipeline**, since the Hub changes continuously.

## Datasets by vertical

| Vertical | Dataset | Status on Hugging Face | Access |
|----------|---------|-------------------------|--------|
| Chest X-ray | **CheXpert** | Official, gated: [`StanfordAIMI/CheXpert-v1.0-512`](https://huggingface.co/datasets/StanfordAIMI/CheXpert-v1.0-512) | Free registration (Stanford AIMI gate) |
| Chest X-ray | **NIH ChestX-ray14** | Unofficial mirror: [`BahaaEldin0/NIH-Chest-Xray-14`](https://huggingface.co/datasets/BahaaEldin0/NIH-Chest-Xray-14) | Open — verify against the [official NIH release](https://nihcc.app.box.com/v/ChestXray-NIHCC) before production use |
| Chest X-ray | **MIMIC-CXR** | Several unofficial derivative subsets exist on HF (e.g. report-generation splits) but **not** the raw gated corpus | Official access is via [PhysioNet](https://physionet.org/content/mimic-cxr/) credentialing (DUA) — do not substitute an unverified HF mirror for a credentialed dataset in a compliance-sensitive pipeline |
| Brain MRI | **BraTS** | Not present on HF Hub as an official release | Official via the [Medical Image Decathlon](http://medicaldecathlon.com/) / [Synapse BraTS challenge pages](https://www.synapse.org/brats) (registration) |
| Lung CT | **LIDC-IDRI / LUNA16** | Not present on HF Hub | Official via [TCIA (LIDC-IDRI)](https://www.cancerimagingarchive.net/collection/lidc-idri/) and [LUNA16 grand-challenge](https://luna16.grand-challenge.org/) |
| Histopathology | **PatchCamelyon** (patch-level CAMELYON derivative) | Open: [`dpdl-benchmark/patch_camelyon`](https://huggingface.co/datasets/dpdl-benchmark/patch_camelyon) | Open |
| Histopathology | **CAMELYON16/17** (full WSIs) | Not present on HF Hub (gigapixel WSIs aren't HF-native) | Official via the [CAMELYON grand-challenge site](https://camelyon17.grand-challenge.org/) |
| ECG | **PTB-XL** | Several unofficial mirrors; largest is [`longisland3/ptb-xl`](https://huggingface.co/datasets/longisland3/ptb-xl) | Official source of record is [PhysioNet PTB-XL](https://physionet.org/content/ptb-xl/) (open, DUA-lite) — use PhysioNet directly for training splits to guarantee fidelity to the official folds |
| ECG | **MIT-BIH Arrhythmia** | Unofficial mirror, explicitly labeled as a clone: [`epr-labs/mit-bih-arrhythmia-database`](https://huggingface.co/datasets/epr-labs/mit-bih-arrhythmia-database) | Official via [PhysioNet MIT-BIH](https://physionet.org/content/mitdb/) |
| Echo | **EchoNet-Dynamic** | Unofficial mirror: [`miyuki17/EchoNet-Dynamic-unzipped`](https://huggingface.co/datasets/miyuki17/EchoNet-Dynamic-unzipped) | Official access requires a Stanford [EchoNet-Dynamic](https://echonet.github.io/dynamic/) data use agreement |
| Dermatology | **HAM10000 / ISIC archive** | Not found as an official release on HF Hub at planning time (re-check — this changes often) | Official via the [ISIC Archive](https://www.isic-archive.com/) |
| Reports/EHR | **MIMIC-III / MIMIC-IV** | Not substituted by any HF mirror — genuinely PHI-adjacent | Official via [PhysioNet](https://physionet.org/content/mimiciv/) credentialing (DUA) |

**Access reality:** several datasets require credentialed access with a PhysioNet
Data Use Agreement (DUA) and CITI training. That paperwork has real lead time —
**start it now, in parallel with MVP**, but do not block the MVP on it. The MVP
runs entirely on fully-open data (CheXpert + NIH ChestX-ray14 for images; a small
open guideline corpus for RAG).

**On unofficial HF mirrors:** several datasets above only exist on the Hub as
community re-uploads, not the data owner's own release. Fine for quick
experimentation, but for anything feeding a promoted model or a compliance-relevant
claim, **pull from the official source** ([12 — Training Plan](12-training-plan.md)
principle 3: fixed, versioned splits) — an unofficial mirror can silently drop,
reformat, or mislabel records relative to the canonical release.

### Data-access plan

1. **Week 0:** register for CheXpert (Stanford AIMI gate) + pull NIH ChestX-ray14
   from the official NIH Box release → unblocks MVP.
2. **Week 0:** begin PhysioNet credentialing (CITI course + DUA) for MIMIC-CXR /
   PTB-XL / MIT-BIH → ~2–4 week lead time, lands in time for verticals #2–3.
3. **BraTS / LUNA16 / CAMELYON / EchoNet-Dynamic / ISIC:** register with the
   respective official source when the corresponding vertical starts.

## Foundation models by vertical — verified Hugging Face links

| Vertical | Primary model | Hugging Face link | Status |
|----------|---------------|--------------------|--------|
| Chest X-ray | **MedGemma 1.5 (4B)** | [`google/medgemma-1.5-4b-it`](https://huggingface.co/google/medgemma-1.5-4b-it) | Official (Google), ready to call now |
| Chest X-ray | MedGemma (27B, larger) | [`google/medgemma-27b-it`](https://huggingface.co/google/medgemma-27b-it) | Official, larger/heavier option if 4B underperforms |
| Chest X-ray (verifier / 2nd opinion) | **CheXpert/NIH-trained DenseNet121** (torchxrayvision) | [`torchxrayvision/densenet121-res224-chex`](https://huggingface.co/torchxrayvision/densenet121-res224-chex), [`-nih`](https://huggingface.co/torchxrayvision/densenet121-res224-nih), [`-all`](https://huggingface.co/torchxrayvision/densenet121-res224-all) | Official releases from the established `torchxrayvision` academic project — ready to use as the heterogeneous critic input ([D6](07-risks-decisions.md)) |
| Brain MRI (interactive refinement) | **MedSAM** | [`wanglab/medsam-vit-base`](https://huggingface.co/wanglab/medsam-vit-base) (original authors) or [`flaviagiammarino/medsam-vit-base`](https://huggingface.co/flaviagiammarino/medsam-vit-base) (`transformers`-native port, easier integration) | Official / official-derived, ready to use |
| Brain MRI / CT / MRI (newer, video-capable) | **MedSAM2** | [`wanglab/MedSAM2`](https://huggingface.co/wanglab/MedSAM2) | Official (wanglab), covers CT/MRI/ultrasound — evaluate as a MedSAM upgrade path |
| Brain MRI (segmentation backbone) | **nnU-Net on BraTS** | No ready-to-use pretrained BraTS checkpoint found on HF Hub at planning time | Train via the nnU-Net framework directly on BraTS per [12 — Training Plan](12-training-plan.md) — nnU-Net ships as a self-configuring *framework*, not a hosted pretrained-weights hub, so this vertical trains its own checkpoint rather than adapting one |
| Lung CT | **CT-FM embeddings** | [`project-lighter/ct_fm_feature_extractor`](https://huggingface.co/project-lighter/ct_fm_feature_extractor), [`project-lighter/ct_fm_segresnet`](https://huggingface.co/project-lighter/ct_fm_segresnet) | Official (project-lighter, the CT-FM authors) — pretrained on 148k+ CT scans, ready to use as embeddings + a lightweight head |
| Histopathology | MedGemma 1.5 (zero-shot) or a MIL head over patches | Use MedGemma links above; no ready-made pathology MIL checkpoint verified on HF at planning time | Zero-shot MedGemma first pass; train a patch-embedding MIL head if it underperforms |
| ECG | 1D-CNN / transformer on PTB-XL | No dominant pretrained ECG foundation model verified on HF at planning time | **Train from scratch** — this is the one vertical without a strong existing checkpoint to adapt (see [12](12-training-plan.md), Vertical 3) |
| Echo | Echo-Vision-FM | No verified HF checkpoint found at planning time — **re-check before committing**, this space moves fast | Evaluate what's newly available when Vertical 6 starts; fall back to training a video model on EchoNet-Dynamic if nothing suitable exists |
| Dermatology | MedGemma 1.5 (zero-shot VLM) | [`google/medgemma-1.5-4b-it`](https://huggingface.co/google/medgemma-1.5-4b-it) | Official, same model as CXR — MedGemma covers dermatology natively |

### Model strategy principles

- **Prefer an existing, verified checkpoint over training from scratch.** Five of
  seven imaging/signal verticals (CXR, Brain MRI refinement via MedSAM, Lung CT,
  Dermatology, and the CXR verifier) have a real, official checkpoint on HF today —
  use it. Only **ECG** currently has no suitable pretrained option and trains from
  scratch ([12 — Training Plan](12-training-plan.md), Vertical 3).
- **The verifier needs a genuinely different model** from the specialist. For CXR,
  that means MedGemma (specialist) vs. `torchxrayvision`'s CheXpert/NIH-trained
  DenseNet121 (critic) — two independently-trained checkpoints, not two prompts on
  the same backbone. Heterogeneity is the whole point ([D6](07-risks-decisions.md)).
- **Every finding carries its locus** (voxel region / ECG lead+interval / WSI
  patch) and a saliency reference. This is a hard requirement for cross-modal
  grounding and for the evidence overlays in the dashboard.
- **Re-verify before pulling into the pipeline.** The Hub changes fast — a model
  card, license, or "last updated" date can shift between planning and
  implementation. Treat every link above as a starting point to re-check
  ([10 — Observability & MLOps](10-observability-mlops.md): nothing enters the
  model registry without this check plus an eval report), not a standing guarantee.

## Sourcing models

Pull weights and model cards from Hugging Face using the links above. Track weight
references with DVC — **never commit weights or any raw data to git**. `data/` and
`models/` hold pointers only ([03 — Tech Stack](03-tech-stack.md)).
