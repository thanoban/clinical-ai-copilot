# Google Colab training notebooks

Colab ports of the notebooks in [../kaggle/](../kaggle/) — same models, same
training/eval code, same metrics tied back to
[docs/12-training-plan.md](../../docs/12-training-plan.md). Only the
**platform-specific parts differ**: GPU runtime setup, Google Drive as
persistent storage (Colab wipes `/content` on disconnect, unlike Kaggle's
attached datasets + `/kaggle/working`), and how each dataset gets onto the
machine (Colab has no "Add Data" mount).

| Notebook | Vertical | Dataset acquisition on Colab |
|----------|----------|-------------------------------|
| [01_ecg_ptbxl_training.ipynb](01_ecg_ptbxl_training.ipynb) | ECG | Direct `wget` from [PhysioNet](https://physionet.org/content/ptb-xl/) — PTB-XL is fully open, no Kaggle account needed |
| [02_pathology_mil_training.ipynb](02_pathology_mil_training.ipynb) | Histopathology | Hugging Face `datasets` (`dpdl-benchmark/patch_camelyon`) — identical to the Kaggle version, no platform-specific step at all |
| [03_brain_mri_nnunet_training.ipynb](03_brain_mri_nnunet_training.ipynb) | Brain MRI | Kaggle API download (bring your own `kaggle.json`) **or** your own copy uploaded to Drive |
| [04_echo_ef_training.ipynb](04_echo_ef_training.ipynb) | Echo | Same two options as BraTS — Kaggle API mirror for prototyping, or the official Stanford release (via DUA) uploaded to Drive |

## Before running any of these

Same four points as [../kaggle/README.md](../kaggle/README.md):

1. **Re-check Hugging Face first** — these notebooks exist because no
   suitable pretrained checkpoint was found at planning time.
2. **Set Runtime → Change runtime type → GPU (T4)** before running anything —
   these notebooks check for a GPU and warn (not fail) if none is detected.
3. **Mount Drive** (every notebook's cell 2) so checkpoints — and, for the
   two notebooks that need it, the downloaded dataset itself — survive a
   disconnect. Free-tier Colab disconnects after ~90 minutes idle and caps
   sessions around 12 hours; none of these training runs should exceed that,
   but a disconnect losing an afternoon's embedding-extraction work is exactly
   what Drive-based caching is there to prevent.
4. None of these notebooks do the full production checklist: subgroup
   breakdown, post-hoc calibration, or model-registry promotion
   ([docs/06](../../docs/06-compliance-safety.md), [docs/10](../../docs/10-observability-mlops.md)).
   They produce a checkpoint; promotion is a separate step.

## Kaggle vs. Colab — which to use

- **Kaggle** if you already have a Kaggle account and the dataset exists as a
  Kaggle "Add Data" mirror — zero download step, and Kaggle's own free-tier
  session limits are slightly more forgiving for a long single run.
- **Colab** if you want Drive-based persistence across multiple shorter
  sessions, need to bring your own officially-licensed data (EchoNet-Dynamic,
  BraTS via Synapse) that isn't on Kaggle, or already have a Colab Pro
  subscription for longer/faster GPU access.

Both produce the same `.pt` checkpoint + `.json` metadata sidecar format —
pick whichever fits your account/compute situation, not a technical constraint
in the code itself.
