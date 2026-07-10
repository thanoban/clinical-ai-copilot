# 04_echo_ef_training.ipynb (Colab) — explained cell by cell

Companion to [04_echo_ef_training.ipynb](04_echo_ef_training.ipynb). Colab
port of
[../kaggle/04_echo_ef_training.ipynb](../kaggle/04_echo_ef_training.ipynb).
Same **re-check Hugging Face first** caveat applies — per
`docs/04-data-models.md`, no Echo-Vision-FM-class checkpoint was verified at
planning time, and this notebook exists as the fallback if that's still true.
The model, frame sampling, training loop, and metrics are identical to Kaggle
and fully explained in
[../kaggle/04_echo_ef_training.explanation.md](../kaggle/04_echo_ef_training.explanation.md).
This file covers what's different: dataset acquisition (same two-path pattern
as the BraTS Colab notebook, for the same underlying reason) and Drive
checkpointing.

## Why this follows the BraTS notebook's pattern, not the ECG one

EchoNet-Dynamic, like BraTS, has no simple open direct-download URL — the
official release requires a Stanford data-use agreement. So this notebook
reuses the exact same **Option A (Kaggle API) / Option B (Drive, official
data)** structure as the BraTS Colab notebook, rather than PTB-XL's simpler
direct-`wget` approach.

---

## Cell 1 (markdown) — overview and the two paths

States the Echo-Vision-FM re-check caveat up front, then the same two
acquisition options as BraTS: Kaggle API for an unofficial mirror (fine for
prototyping), or your own Drive-hosted copy obtained through the official DUA
(recommended beyond prototyping).

## Cell 2 (code) — install dependencies

```python
!pip install -q opencv-python-headless
```

Identical to the Kaggle notebook's cell 2.

## Cell 3 (code) — mount Drive

```python
from google.colab import drive
drive.mount("/content/drive")

import os
DRIVE_WORKDIR = "/content/drive/MyDrive/aegis-dx/echo-ef"
os.makedirs(DRIVE_WORKDIR, exist_ok=True)
```

Same Drive-mount pattern as every Colab notebook in this set — used here for
the trained checkpoint only (unlike the BraTS notebook's separate
results-only directory, this one folder holds everything since EF regression
doesn't produce nnU-Net-scale intermediate files).

## Cell 4 (markdown) — Option A, Kaggle API

Same process as the BraTS notebook: create a Kaggle API token, upload it,
search *kaggle.com/datasets* for "EchoNet-Dynamic," and copy the exact API
command from the dataset page.

## Cell 5 (code) — Option A: Kaggle API download

```python
from google.colab import files

os.makedirs("/root/.kaggle", exist_ok=True)
uploaded = files.upload()  # select your kaggle.json when prompted
!mv kaggle.json /root/.kaggle/kaggle.json
!chmod 600 /root/.kaggle/kaggle.json

KAGGLE_DATASET_SLUG = "REPLACE_WITH_SLUG_FROM_KAGGLE_DATASET_PAGE"  # fill this in - see markdown above

!pip install -q kaggle
!kaggle datasets download -d {KAGGLE_DATASET_SLUG} -p /content/echonet_download --unzip
ECHONET_ROOT = "/content/echonet_download"
print("Downloaded to:", ECHONET_ROOT)
```

**What/why:** Mechanically identical to the BraTS notebook's Kaggle-API cell —
see
[03_brain_mri_nnunet_training.explanation.md](03_brain_mri_nnunet_training.explanation.md)'s
cell 5 for why `files.upload()`, `chmod 600`, and `--unzip` are each there. One
difference worth noting: `KAGGLE_DATASET_SLUG` is left as an explicit
`"REPLACE_WITH_SLUG_FROM_KAGGLE_DATASET_PAGE"` placeholder here, rather than a
filled-in example — a deliberate choice, since EchoNet-Dynamic mirrors on
Kaggle are less consistently maintained than the well-known BraTS2020 mirror
used as an example in the other notebook, so a stale guessed slug would be
more likely to mislead than help.

## Cell 6 (markdown) — Option B, official data

Recommends this path explicitly for anything beyond prototyping — go through
Stanford's DUA, download `FileList.csv` + `Videos/`, upload once to Drive.

## Cell 7 (code) — Option B: point at Drive

```python
# ECHONET_ROOT = "/content/drive/MyDrive/aegis-dx/echonet-dynamic-official"
print("ECHONET_ROOT is set to:", ECHONET_ROOT)
```

Same activate-by-uncommenting pattern as the BraTS notebook's equivalent cell —
everything downstream only ever references `ECHONET_ROOT`, regardless of which
option populated it.

## Cell 8 (code) — imports and reproducibility

Identical to the Kaggle notebook's cell 3 (same seeding, same imports,
including `torchvision.models` for the pretrained ResNet18 encoder used later).

## Cell 9 (code) — locate FileList.csv and Videos/

```python
file_list_candidates = glob.glob(f"{ECHONET_ROOT}/**/FileList.csv", recursive=True)
if not file_list_candidates:
    raise FileNotFoundError(f"No FileList.csv found under {ECHONET_ROOT}. Check cell 3 or 4 above.")
ECHONET_ROOT = os.path.dirname(file_list_candidates[0])

VIDEOS_DIR = os.path.join(ECHONET_ROOT, "Videos")
if not os.path.isdir(VIDEOS_DIR):
    nested = glob.glob(os.path.join(ECHONET_ROOT, "**", "Videos"), recursive=True)
    VIDEOS_DIR = nested[0] if nested else VIDEOS_DIR
print("EchoNet root:", ECHONET_ROOT)
print("Videos dir:", VIDEOS_DIR)
```

**What/why:** The Kaggle version searches `/kaggle/input` directly; this
version searches within whichever `ECHONET_ROOT` was set by Option A or
Option B above — otherwise identical logic, including the same nested-`Videos/`
fallback for mirrors that add an extra folder level. Note that
`ECHONET_ROOT` gets **reassigned** here to the actual directory containing
`FileList.csv` (which might be a subfolder of what Option A's download path or
Option B's Drive path pointed at) — this normalization step is what lets every
later cell use a clean, consistent path regardless of exactly how the source
data was organized.

## Cells 10–13 — split, Dataset, model, training

**Identical to the Kaggle notebook's cells 7, 8, 9, 10** — same official
`FileList.csv` `Split` column usage, same frame-sampling `EchoNetDataset`
(16 evenly-spaced frames, 112x112, normalized to `[-1, 1]`), same
`EchoEFRegressor` (fine-tuned ResNet18 per-frame encoder + temporal attention
pooling + sigmoid regression head), same `L1Loss`/`AdamW` setup. See
[../kaggle/04_echo_ef_training.explanation.md](../kaggle/04_echo_ef_training.explanation.md)
cells 5, 7, 9, 11 for the full reasoning — none of it changes with the platform.

## Cell 13 continued — Drive checkpointing

```python
CHECKPOINT_PATH = os.path.join(DRIVE_WORKDIR, "echonet_ef_regressor_best.pt")
...
    if val_mae < best_val_mae:
        best_val_mae = val_mae
        torch.save(model.state_dict(), CHECKPOINT_PATH)

model.load_state_dict(torch.load(CHECKPOINT_PATH))
```

**What/why:** Same "write to Drive on every improvement" pattern as the other
three Colab notebooks — see
[01_ecg_ptbxl_training.explanation.md](01_ecg_ptbxl_training.explanation.md)'s
cell 10 for the full reasoning. Note the comparison direction: `<` here, not
`>` — MAE is an error metric (lower is better), unlike the AUROC-based
notebooks, which is worth double-checking any time you copy this
checkpointing pattern into a new notebook for a different metric.

## Cell 14 (code) — held-out test evaluation + metadata

```python
test_mae, test_r2 = evaluate(test_loader)
print(f"Test EF MAE: {test_mae:.2f} percentage points")
print(f"Test R^2: {test_r2:.4f}")

metadata = {
    "model": "EchoEFRegressor",
    "num_frames_sampled": NUM_FRAMES,
    "frame_size": FRAME_SIZE,
    "test_ef_mae": float(test_mae),
    "test_r2": float(test_r2),
    "trained_on": "EchoNet-Dynamic, official FileList.csv Split column",
    "trained_on_platform": "Google Colab",
}
with open(os.path.join(DRIVE_WORKDIR, "echonet_ef_regressor_best.json"), "w") as handle:
    json.dump(metadata, handle, indent=2)
print(json.dumps(metadata, indent=2))
```

**What/why:** Same MAE + R² reporting as Kaggle (see that explanation for why
both matter, not just one), same metadata sidecar with `"trained_on_platform":
"Google Colab"` added for registry-provenance tracking.

## Cell 15 (markdown) — next steps

Same list as Kaggle: re-check for an Echo-Vision-FM checkpoint before
committing further to this training path; add the wall-motion classification
head this notebook doesn't build; subgroup breakdown, calibration, registry
entry; switch from an unofficial mirror to the official Stanford release
before anything beyond internal experimentation.

## Final summary

This notebook and the BraTS Colab notebook share the same underlying lesson:
when a dataset has no simple open access route, "port to Colab" means
designing an explicit acquisition choice for the user to make (Kaggle API vs.
your own officially-obtained copy), not just relocating a path. Once that
choice is resolved into a single root directory variable, every remaining cell
— the actual modeling work — is identical to its Kaggle counterpart.
