# 03_brain_mri_nnunet_training.ipynb — explained cell by cell

Companion to [03_brain_mri_nnunet_training.ipynb](03_brain_mri_nnunet_training.ipynb).
This is the **heaviest** notebook in the set — nnU-Net is a self-configuring
framework, not a hand-written PyTorch loop, so most cells here call nnU-Net's
own CLI commands rather than defining a model directly. Read the notebook's
own compute-cost warning before running anything: a full BraTS run is a
multi-day, multi-GPU job; this notebook trains **one fold, a reduced epoch
budget**, to prove the pipeline, not to produce a benchmark result.

## How to read this file

Each cell's code is shown exactly as it appears in the notebook, followed by an
explanation of the mechanics and the reasoning.

---

## Cell 1 (markdown) — overview and warnings

States the plan-level context (per `docs/04-data-models.md`, no pretrained
BraTS checkpoint exists on Hugging Face, so nnU-Net trains its own), the
compute-cost warning from `docs/07-risks-decisions.md`, and that nnU-Net is
driven through CLI commands rather than a Python training loop by design — the
framework picks patch size, batch size, and network depth for you based on the
dataset's own properties.

## Cell 2 (code) — install nnU-Net v2

```python
!pip install -q nnunetv2
```

**What/why:** `nnunetv2` bundles both the Python library and the command-line
tools (`nnUNetv2_plan_and_preprocess`, `nnUNetv2_train`, `nnUNetv2_predict`)
used throughout the rest of this notebook — installing the one package gets
you both.

## Cell 3 (code) — nnU-Net environment variables

```python
import glob, json, os, shutil
import nibabel as nib
import numpy as np

NNUNET_BASE = "/kaggle/working/nnunet"
os.environ["nnUNet_raw"] = f"{NNUNET_BASE}/nnUNet_raw"
os.environ["nnUNet_preprocessed"] = f"{NNUNET_BASE}/nnUNet_preprocessed"
os.environ["nnUNet_results"] = f"{NNUNET_BASE}/nnUNet_results"

for path in os.environ["nnUNet_raw"], os.environ["nnUNet_preprocessed"], os.environ["nnUNet_results"]:
    os.makedirs(path, exist_ok=True)

DATASET_ID = 1
DATASET_NAME = f"Dataset{DATASET_ID:03d}_BraTS"
DATASET_DIR = os.path.join(os.environ["nnUNet_raw"], DATASET_NAME)
os.makedirs(os.path.join(DATASET_DIR, "imagesTr"), exist_ok=True)
os.makedirs(os.path.join(DATASET_DIR, "labelsTr"), exist_ok=True)
print("nnU-Net dataset dir:", DATASET_DIR)
```

**What/why:** nnU-Net doesn't take these paths as function arguments or a
config file — it reads them **exclusively from environment variables**, and it
does so at import/CLI-invocation time, which is why these three `os.environ[...]`
assignments must happen before any `!nnUNetv2_*` command runs later in the
notebook. `DATASET_ID`/`DATASET_NAME` follow nnU-Net's mandatory naming
convention — every dataset it manages must be named `DatasetXXX_Name` with a
3-digit zero-padded ID (`f"{DATASET_ID:03d}"` produces `"001"`), because
nnU-Net looks up datasets by this exact ID elsewhere (the `-d {DATASET_ID}`
flag in later cells). Creating `imagesTr`/`labelsTr` upfront just avoids a
`FileNotFoundError` from `shutil.copy` in the next cell.

## Cell 4 (markdown) — locate BraTS and convert

Explains what nnU-Net expects per case (four modality files named
`_0000`–`_0003`, one label file) and the BraTS label convention (1=necrotic
core, 2=edema, 4=enhancing tumor) that needs remapping to consecutive integers.

## Cell 5 (code) — find BraTS case folders

```python
MODALITY_KEYWORDS = {"t1": 0, "t1ce": 1, "t2": 2, "flair": 3}

seg_files = glob.glob("/kaggle/input/**/*seg.nii.gz", recursive=True) + glob.glob(
    "/kaggle/input/**/*seg.nii", recursive=True
)
if not seg_files:
    raise FileNotFoundError(
        "No BraTS segmentation files found under /kaggle/input. "
        "Add a BraTS dataset via 'Add Data', or adjust the glob pattern above "
        "to match your specific mirror's folder layout."
    )
case_dirs = sorted({os.path.dirname(path) for path in seg_files})
print(f"Found {len(case_dirs)} BraTS case folders. Example: {case_dirs[0]}")

MAX_CASES = 60
case_dirs = case_dirs[:MAX_CASES]
print(f"Using {len(case_dirs)} cases for this run.")
```

**What/why:** `MODALITY_KEYWORDS` maps each MRI sequence name to nnU-Net's
required **channel index** — this ordering (0=T1, 1=T1ce, 2=T2, 3=FLAIR)
must exactly match what `dataset.json` declares later (cell 7), or nnU-Net
will silently train on mismatched channels. Searching for `*seg.nii(.gz)`
files rather than a specific folder name is the same "search, don't hardcode"
approach used for PTB-XL — different BraTS Kaggle mirrors organize folders
differently, but every case ships exactly one segmentation file, making it a
reliable anchor. `sorted({os.path.dirname(path) for path in seg_files})` — the
set comprehension deduplicates in case a mirror has more than one seg-like
file per case, then `sorted()` makes the case ordering deterministic across
runs (important since `MAX_CASES = 60` then takes a **prefix** of this list —
without sorting, a different 60 cases could be selected on each notebook run).
`MAX_CASES` exists purely to fit a Kaggle session's time budget; the
notebook's own warning is explicit that this makes the result a pipeline
smoke test, not a real training result.

## Cell 6 (code) — convert to nnU-Net's layout

```python
def find_modality_file(case_dir: str, keyword: str) -> str | None:
    matches = [
        f for f in glob.glob(os.path.join(case_dir, "*.nii*"))
        if keyword in os.path.basename(f).lower() and "seg" not in os.path.basename(f).lower()
    ]
    return matches[0] if matches else None


def remap_brats_labels(segmentation: np.ndarray) -> np.ndarray:
    remapped = segmentation.copy()
    remapped[segmentation == 4] = 3
    return remapped


converted_case_ids = []
for case_dir in case_dirs:
    case_id = os.path.basename(case_dir.rstrip("/"))
    modality_paths = {keyword: find_modality_file(case_dir, keyword) for keyword in MODALITY_KEYWORDS}
    if any(path is None for path in modality_paths.values()):
        print(f"skip {case_id}: missing a modality file")
        continue

    seg_path = glob.glob(os.path.join(case_dir, "*seg.nii*"))[0]

    for keyword, channel_index in MODALITY_KEYWORDS.items():
        destination = os.path.join(DATASET_DIR, "imagesTr", f"{case_id}_{channel_index:04d}.nii.gz")
        shutil.copy(modality_paths[keyword], destination)

    seg_image = nib.load(seg_path)
    seg_data = remap_brats_labels(np.asarray(seg_image.dataobj))
    remapped_image = nib.Nifti1Image(seg_data.astype(np.uint8), seg_image.affine, seg_image.header)
    nib.save(remapped_image, os.path.join(DATASET_DIR, "labelsTr", f"{case_id}.nii.gz"))

    converted_case_ids.append(case_id)

print(f"Converted {len(converted_case_ids)} cases.")
```

**What/why:** `"seg" not in os.path.basename(f).lower()` in `find_modality_file`
is a small but important exclusion — without it, a filename like
`patient01_t1_seg.nii.gz` (if a mirror names things that way) could match the
`t1` keyword search and get miscategorized as a modality image instead of the
label file. `remap_brats_labels` is the fix for a real nnU-Net requirement:
**label values must be consecutive integers starting at 0** — BraTS's raw
convention uses `{0, 1, 2, 4}` (skipping 3), so `remapped[segmentation == 4] =
3` closes that gap; skip this step and nnU-Net's own dataset-integrity check
in cell 8 will reject the data. `seg_image.affine` and `seg_image.header` are
carried over unchanged into the remapped image — these encode the scan's
physical spacing and orientation in 3D space, and losing them would silently
corrupt how nnU-Net interprets voxel geometry, even though the label *values*
would look fine on inspection. The `f"{case_id}_{channel_index:04d}.nii.gz"`
filename pattern (`_0000`, `_0001`, etc.) is nnU-Net's exact required naming
convention for multi-channel inputs — get the zero-padding width wrong and
nnU-Net won't recognize the files as belonging together.

## Cell 7 (markdown) — dataset.json

Explains that this manifest declares the modalities (channel order must match
the `_0000.._0003` suffixes), the label map, and the case count — what nnU-Net's
planner reads to decide preprocessing and network configuration automatically.

## Cell 8 (code) — write the manifest

```python
dataset_json = {
    "channel_names": {"0": "T1", "1": "T1ce", "2": "T2", "3": "FLAIR"},
    "labels": {
        "background": 0,
        "necrotic_core": 1,
        "edema": 2,
        "enhancing_tumor": 3,
    },
    "numTraining": len(converted_case_ids),
    "file_ending": ".nii.gz",
}
with open(os.path.join(DATASET_DIR, "dataset.json"), "w") as handle:
    json.dump(dataset_json, handle, indent=2)
print(json.dumps(dataset_json, indent=2))
```

**What/why:** Every key here is load-bearing, not decorative. `channel_names`'
keys (`"0"`, `"1"`, ...) must match the `_0000`/`_0001` suffixes from cell 6
exactly — nnU-Net cross-checks these. `labels` must list consecutive integers
starting at `background: 0` (the remapping from cell 6 is what makes this
true). `numTraining` has to match the actual number of case IDs converted, or
nnU-Net's integrity check (next cell) will flag a mismatch and refuse to
proceed — which is a deliberate nnU-Net safety feature, catching a
half-converted dataset before you spend GPU hours training on it.

## Cell 9 (code) — plan & preprocess

```python
!nnUNetv2_plan_and_preprocess -d {DATASET_ID} --verify_dataset_integrity -c 3d_fullres
```

**What/why:** This single command does three things nnU-Net is specifically
known for: it inspects your dataset's voxel spacing, image size, and modality
intensity statistics; **automatically decides** patch size, batch size, and
network depth to fit those properties (the "self-configuring" part `docs/12`
references); and preprocesses every case into the exact tensor format the
training step expects. `--verify_dataset_integrity` runs the sanity checks
implied by cell 8's explanation — catching missing files, label mismatches, or
`numTraining` discrepancies here, before training, is far cheaper than
discovering them mid-run. `-c 3d_fullres` scopes this to nnU-Net's full-resolution
3D configuration specifically (nnU-Net can also plan 2D or 3D-lowres
configurations for other datasets — BraTS is a natural fit for 3D fullres,
which is why the notebook doesn't bother planning the alternatives).

## Cell 10 (markdown) — train, one fold, reduced budget

Explains real nnU-Net training defaults to 5-fold cross-validation at 1000
epochs per fold — this notebook trains fold 0 only, with a reduced-epoch
trainer variant, purely as a pipeline smoke test.

## Cell 11 (code) — train fold 0

```python
!nnUNetv2_train {DATASET_ID} 3d_fullres 0 -tr nnUNetTrainer_50epochs
```

**What/why:** The `0` here selects **fold 0 of 5** — nnU-Net automatically
partitions your training cases into 5 cross-validation folds during the
plan-and-preprocess step, and this command trains only one of them.
`nnUNetTrainer_50epochs` is a real trainer class that ships inside `nnunetv2`
specifically for quicker runs (the notebook's comment calls this out
explicitly) — swapping it back to the plain `nnUNetTrainer` class (no suffix)
reverts to the full 1000-epoch schedule once you have a real training budget.
This is the one command in the whole notebook set that can genuinely take
hours even in its reduced form, because 3D patch-based training is
compute-heavy regardless of epoch count.

## Cell 12 (markdown) — inference on a held-out case

Flags explicitly that the "held-out" case used here is actually a training
case reused for a smoke test, not a real held-out set — a real promotion gate
needs cases nnU-Net genuinely never saw.

## Cell 13 (code) — run inference

```python
INFERENCE_INPUT_DIR = f"{NNUNET_BASE}/inference_input"
INFERENCE_OUTPUT_DIR = f"{NNUNET_BASE}/inference_output"
os.makedirs(INFERENCE_INPUT_DIR, exist_ok=True)
os.makedirs(INFERENCE_OUTPUT_DIR, exist_ok=True)

sample_case_id = converted_case_ids[0]
for channel_index in range(4):
    source = os.path.join(DATASET_DIR, "imagesTr", f"{sample_case_id}_{channel_index:04d}.nii.gz")
    shutil.copy(source, INFERENCE_INPUT_DIR)

!nnUNetv2_predict -i {INFERENCE_INPUT_DIR} -o {INFERENCE_OUTPUT_DIR} -d {DATASET_ID} -c 3d_fullres -f 0 -tr nnUNetTrainer_50epochs
print("Predicted files:", os.listdir(INFERENCE_OUTPUT_DIR))
```

**What/why:** `nnUNetv2_predict` needs the **same** `-c`, `-f`, and `-tr` flags
used during training (`3d_fullres`, fold `0`, `nnUNetTrainer_50epochs`) so it
loads the matching trained weights rather than looking for a different
configuration that was never trained. Copying only the four `_0000.._0003`
image files (not the label) into `INFERENCE_INPUT_DIR` mirrors exactly what a
real deployment would have available at prediction time — you never have the
ground-truth segmentation when actually running inference on a new patient.

## Cell 14 (markdown) — locate the checkpoint and results

Notes that nnU-Net manages its own checkpoint/log directory structure under
`nnUNet_results` — nothing to hand-serialize.

## Cell 15 (code) — find the checkpoint + summary

```python
checkpoint_paths = glob.glob(f"{os.environ['nnUNet_results']}/**/checkpoint_final.pth", recursive=True)
summary_paths = glob.glob(f"{os.environ['nnUNet_results']}/**/summary.json", recursive=True)

print("Checkpoint(s):", checkpoint_paths)
print("Summary file(s):", summary_paths)

if summary_paths:
    with open(summary_paths[0]) as handle:
        summary = json.load(handle)
    print("Mean Dice per class:", summary.get("mean", {}))
```

**What/why:** Unlike the ECG and pathology notebooks, there's no explicit
`torch.save(...)` call here — nnU-Net writes `checkpoint_final.pth` itself as
part of the training command in cell 11, following its own internal directory
layout (`nnUNet_results/<dataset>/<trainer>__<plans>__<config>/fold_0/`). This
cell just **locates** what nnU-Net already produced rather than creating
anything new. `summary.json` is nnU-Net's own validation report, generated
automatically at the end of training — `summary.get("mean", {})` pulls the
mean Dice score per class directly from it, so you don't have to compute Dice
yourself the way the other notebooks compute AUROC by hand.

## Cell 16 (markdown) — next steps

Lists the real gap between this notebook and a promotable model: use the full
case set (not 60), the default 1000-epoch trainer, and all 5 folds on a
multi-GPU box; compare against published nnU-Net BraTS baselines; report
Dice + Hausdorff distance per tumor sub-region, not just an aggregate; then
pair the trained model with MedSAM/MedSAM2 (usable as-is, no training needed)
for interactive refinement in the dashboard.

## Final summary

This notebook is structurally different from the other three: instead of
writing a training loop, most of the work is **data engineering** (converting
BraTS's folder layout and label convention into exactly what nnU-Net expects)
followed by invoking a framework that configures and trains itself. The
discipline that matters most here isn't algorithmic — it's getting the file
naming, channel ordering, and label remapping exactly right, since nnU-Net's
own integrity checks will only catch some kinds of mismatches, not all of them.
