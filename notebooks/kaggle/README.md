# Kaggle training notebooks

Runnable Kaggle notebooks for the components in [docs/12-training-plan.md](../../docs/12-training-plan.md)
that need training rather than an off-the-shelf checkpoint. See
[docs/04-data-models.md](../../docs/04-data-models.md) for which checkpoints
need *no* training at all (MedGemma, torchxrayvision, MedSAM/MedSAM2, CT-FM).

| Notebook | Vertical | Training type | Kaggle GPU budget |
|----------|----------|----------------|--------------------|
| [01_ecg_ptbxl_training.ipynb](01_ecg_ptbxl_training.ipynb) | ECG | From scratch (the one genuine gap) | Single GPU, a few hours |
| [02_pathology_mil_training.ipynb](02_pathology_mil_training.ipynb) | Histopathology | Light — only the MIL aggregator head; embedding backbone frozen | Single GPU, ~1 hour |
| [03_brain_mri_nnunet_training.ipynb](03_brain_mri_nnunet_training.ipynb) | Brain MRI | Light in framework terms, heaviest in compute — nnU-Net on BraTS | Single GPU for a pipeline smoke test; **a full run needs multi-day/multi-GPU**, see the notebook's own caveat |
| [04_echo_ef_training.ipynb](04_echo_ef_training.ipynb) | Echo | Conditional from scratch — only if no Echo-Vision-FM checkpoint turns up on re-check | Single GPU, a few hours |

## Before running any of these

1. **Re-check Hugging Face first.** These notebooks exist because no suitable
   pretrained checkpoint was found at planning time — that can change. Don't
   spend GPU hours training something that already exists.
2. Each notebook auto-detects its dataset's path under `/kaggle/input` rather
   than hardcoding a specific mirror's slug — add the dataset via Kaggle's
   *Add Data* search (see each notebook's setup cell for the exact search term).
3. None of these notebooks do the full production checklist: subgroup
   breakdown, post-hoc calibration, or model-registry promotion
   ([docs/06](../../docs/06-compliance-safety.md), [docs/10](../../docs/10-observability-mlops.md)).
   They produce a checkpoint; promotion is a separate step.
4. Download the `.pt` checkpoint (and its `.json` metadata sidecar) from
   Kaggle's *Output* tab when done. Track it with DVC, never commit it to git
   ([docs/03](../../docs/03-tech-stack.md)).
