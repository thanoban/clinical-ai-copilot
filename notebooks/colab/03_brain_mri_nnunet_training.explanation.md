# 03_brain_mri_nnunet_training.ipynb (Colab) — explained cell by cell

Companion to [03_brain_mri_nnunet_training.ipynb](03_brain_mri_nnunet_training.ipynb).
Colab port of
[../kaggle/03_brain_mri_nnunet_training.ipynb](../kaggle/03_brain_mri_nnunet_training.ipynb).
**Read the compute-cost warning in the Kaggle explanation first** — it applies
unchanged here: a full nnU-Net BraTS run is multi-day, multi-GPU work; this
notebook trains one fold as a pipeline smoke test. The nnU-Net mechanics (plan
& preprocess, fold training, inference, locating results) are identical to
Kaggle and explained in
[../kaggle/03_brain_mri_nnunet_training.explanation.md](../kaggle/03_brain_mri_nnunet_training.explanation.md).
This file focuses on the one thing that's genuinely different: **getting
BraTS onto a Colab machine at all**, since Colab has no "Add Data" mount.

## Why dataset acquisition is harder here than for ECG or pathology

PTB-XL (Colab notebook 01) is fully open, so a direct `wget` from PhysioNet
works. PatchCamelyon (Colab notebook 02) loads straight from Hugging Face.
BraTS has neither option: there's no simple open direct-download URL, and the
official route (Synapse registration + data-use agreement) isn't something a
notebook can automate. So this notebook offers **two acquisition paths** and
lets you pick based on what you already have access to.

---

## Cell 1 (markdown) — overview and the two acquisition options

Lays out **Option A** (Kaggle API — download a Kaggle BraTS mirror the same
way you'd add it on Kaggle, just via API calls instead of the UI) and
**Option B** (Drive — if you've already obtained BraTS through Synapse and
uploaded it yourself). Also repeats the compute-cost warning from the Kaggle
version, since Colab's session limits are, if anything, less forgiving than
Kaggle's for a long single run.

## Cell 2 (code) — install nnU-Net v2

```python
!pip install -q nnunetv2
```

Identical to the Kaggle notebook's cell 2.

## Cell 3 (code) — mount Drive (results only)

```python
from google.colab import drive
drive.mount("/content/drive")

import os
DRIVE_RESULTS_DIR = "/content/drive/MyDrive/aegis-dx/brain-mri-nnunet/results"
os.makedirs(DRIVE_RESULTS_DIR, exist_ok=True)
```

**What/why — a deliberately different persistence strategy than the other
three Colab notebooks.** Here, only the **final results** get a Drive path
upfront; nnU-Net's raw/preprocessed intermediate files (which can be large —
multiple gigabytes for even a modest case count) stay on local Colab disk
throughout training. This is a genuine trade-off: local disk is faster to
read/write during training (nnU-Net does a lot of small file I/O while
planning and preprocessing) and Drive-mounted storage adds real latency for
that kind of access pattern. The intermediate files are also fully
**re-derivable** from the raw BraTS data plus this notebook, so losing them to
a disconnect costs re-running a few cells, not losing irreplaceable work —
unlike the trained checkpoint itself, which does get copied to Drive at the
very end (cell 12).

## Cell 4 (markdown) — Option A, Kaggle API

Explains the three-step process: create a Kaggle API token at
kaggle.com/settings, upload it when prompted, then find the exact dataset
slug via the "Copy API command" button on a BraTS mirror's dataset page rather
than guessing one, since Kaggle dataset slugs for a given mirror can change
over time.

## Cell 5 (code) — Option A: Kaggle API download

```python
from google.colab import files

os.makedirs("/root/.kaggle", exist_ok=True)
uploaded = files.upload()  # select your kaggle.json when prompted
!mv kaggle.json /root/.kaggle/kaggle.json
!chmod 600 /root/.kaggle/kaggle.json

KAGGLE_DATASET_SLUG = "awsaf49/brats20-dataset-training-validation"  # example - verify this still exists and matches BraTS's expected layout before trusting it

!pip install -q kaggle
!kaggle datasets download -d {KAGGLE_DATASET_SLUG} -p /content/brats_download --unzip
BRATS_SOURCE_DIR = "/content/brats_download"
print("Downloaded to:", BRATS_SOURCE_DIR)
```

**What/why — this is the notebook's most Colab-specific cell.**
`files.upload()` opens a browser file picker specifically for uploading local
files *into* the Colab session — this is how a `kaggle.json` API token
(downloaded to your own computer from Kaggle's settings page) gets onto the
Colab VM at all, since Colab has no equivalent of Kaggle's own built-in API
credential handling. The Kaggle CLI expects its credentials at exactly
`~/.kaggle/kaggle.json` with restrictive permissions — `chmod 600` (owner
read/write only) isn't cosmetic; the Kaggle CLI actively refuses to run if it
finds world-readable credentials, as a safeguard against accidentally leaking
your API token on a shared machine. `KAGGLE_DATASET_SLUG` is filled in with a
real, commonly-cited BraTS2020 Kaggle dataset as a working example — but the
inline comment is a deliberate hedge: Kaggle dataset availability and slugs
genuinely do change, so this should be verified against the actual dataset
page before you trust it blindly, exactly the same "re-verify before trusting"
discipline applied to every pretrained-model link elsewhere in this project's
docs. `--unzip` has the Kaggle CLI extract the downloaded archive
automatically rather than leaving you a `.zip` to handle in a separate step.

## Cell 6 (markdown) — Option B, Drive

Explicitly recommends this path for anything beyond prototyping, since it
means using data obtained through BraTS's actual official channel (Synapse,
with its own registration and data-use agreement) rather than an unverified
community mirror.

## Cell 7 (code) — Option B: point at Drive

```python
# BRATS_SOURCE_DIR = "/content/drive/MyDrive/aegis-dx/brats-raw"
print("BRATS_SOURCE_DIR is set to:", BRATS_SOURCE_DIR)
```

**What/why:** This cell is intentionally mostly a comment — it's a template
you activate by uncommenting the assignment (and skipping cell 5 instead),
not something meant to run as-is alongside Option A. Whichever option you use,
every cell after this one only ever references the `BRATS_SOURCE_DIR`
variable, not `/kaggle/input` or any Kaggle-specific path — that's the seam
that lets the rest of the notebook stay identical regardless of which
acquisition path you took.

## Cells 8–14 — nnU-Net setup, conversion, planning, training, inference

**Identical to the Kaggle notebook's cells 3–13**, with exactly one textual
difference: every `glob.glob("/kaggle/input/**/...")` search is replaced with
`glob.glob(f"{BRATS_SOURCE_DIR}/**/...")`. Everything else — the
`MODALITY_KEYWORDS` mapping, the BraTS label remapping (`4 → 3`), the
`dataset.json` manifest, the `nnUNetv2_plan_and_preprocess` /
`nnUNetv2_train` / `nnUNetv2_predict` commands, the reduced-epoch
`nnUNetTrainer_50epochs` variant — is explained in full in
[../kaggle/03_brain_mri_nnunet_training.explanation.md](../kaggle/03_brain_mri_nnunet_training.explanation.md).
The one operational note specific to Colab: this training cell is the
longest-running command in the whole notebook, and Colab's idle-disconnect
timeout is stricter than Kaggle's — keeping the browser tab active (or using
Colab Pro's background execution, if available) matters more here than on
Kaggle.

## Cell 15 (code) — copy final results to Drive

```python
shutil.copytree(os.environ["nnUNet_results"], DRIVE_RESULTS_DIR, dirs_exist_ok=True)

summary_paths = glob.glob(f"{DRIVE_RESULTS_DIR}/**/summary.json", recursive=True)
if summary_paths:
    with open(summary_paths[0]) as handle:
        summary = json.load(handle)
    print("Mean Dice per class:", summary.get("mean", {}))
print("Results copied to:", DRIVE_RESULTS_DIR)
```

**What/why — the payoff of the persistence strategy chosen in cell 3.** Now
that training has actually finished, the (comparatively small) trained
checkpoint and its summary metrics get copied from local disk to
`DRIVE_RESULTS_DIR` in one step. `dirs_exist_ok=True` lets this run safely even
if you're re-running the notebook and the destination folder already has an
earlier run's results in it — `shutil.copytree` would otherwise raise if the
target directory already existed. This is the one point in the whole notebook
where the local, fast-but-ephemeral working directory and the slow-but-durable
Drive directory actually meet.

## Cell 16 (markdown) — next steps

Same list as the Kaggle version: this is a pipeline smoke test, not a trained
model; scale to the full case set, default trainer, and 5 folds on a
multi-GPU box before comparing against published nnU-Net BraTS Dice
baselines; report per-sub-region Dice + Hausdorff distance; pair with
MedSAM/MedSAM2 for interactive refinement once trained.

## Final summary

This is the notebook where "porting to Colab" meant genuinely rethinking a
step, not just relocating file paths — because BraTS has no simple open
access route, the notebook has to offer a real choice (Kaggle API vs. your own
Drive-hosted copy) rather than a single automated path. Once that choice is
made, though, everything downstream — the actual nnU-Net training pipeline —
is exactly the same regardless of platform, which is why it isn't re-explained
here.
