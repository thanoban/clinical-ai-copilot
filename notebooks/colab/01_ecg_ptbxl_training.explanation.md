# 01_ecg_ptbxl_training.ipynb (Colab) — explained cell by cell

Companion to [01_ecg_ptbxl_training.ipynb](01_ecg_ptbxl_training.ipynb). This
is the Colab port of
[../kaggle/01_ecg_ptbxl_training.ipynb](../kaggle/01_ecg_ptbxl_training.ipynb)
— the model, loss, training loop, and evaluation code are **identical** to the
Kaggle version (see
[../kaggle/01_ecg_ptbxl_training.explanation.md](../kaggle/01_ecg_ptbxl_training.explanation.md)
for the full reasoning behind those cells). This file focuses on what's
genuinely different here: **how the dataset gets onto the machine, and how the
run survives a disconnect** — the two things that actually change between
Kaggle and Colab.

## Why this notebook looks different at all

Kaggle attaches datasets to `/kaggle/input` through its UI and gives you
`/kaggle/working` as a persistent output folder for the life of the session.
Colab has neither: there's no dataset-mount UI, and `/content` is wiped the
moment the runtime disconnects. Everything below that isn't in the Kaggle
version exists to work around exactly those two facts.

---

## Cell 1 (markdown) — overview and Colab setup

Points out that PTB-XL is **fully open** — a quick PhysioNet registration, no
Kaggle account or data-use agreement needed — which is why this notebook can
download it directly rather than needing the Kaggle-API workaround the
BraTS/Echo Colab notebooks use. Also explains Colab's free-tier session
behavior: disconnects after ~90 minutes idle, caps around 12 hours, which is
why Drive-based checkpointing (cell 10) matters here specifically.

## Cell 2 (code) — install dependencies

```python
!pip install -q wfdb neurokit2
```

Identical to the Kaggle notebook's cell 2 — see that explanation for what each
package does.

## Cell 3 (code) — mount Google Drive

```python
from google.colab import drive
drive.mount("/content/drive")

import os
DRIVE_WORKDIR = "/content/drive/MyDrive/aegis-dx/ecg-ptbxl"
os.makedirs(DRIVE_WORKDIR, exist_ok=True)
print("Persistent working dir:", DRIVE_WORKDIR)
```

**What/why — this is the first genuinely Colab-specific cell.**
`drive.mount(...)` triggers a one-time OAuth flow (a browser popup asking you
to authorize Colab's access to your Google Drive) and then makes your Drive
files available as a regular filesystem path under `/content/drive`. Unlike
`/content` itself, **anything under `/content/drive/MyDrive` persists across
disconnects** — it's your actual Drive storage, not the ephemeral VM disk. The
notebook creates one dedicated subfolder (`aegis-dx/ecg-ptbxl`) rather than
writing loose files into the top level of your Drive, so all of this
notebook's outputs — the downloaded dataset, the trained checkpoint, the
metadata — stay organized together and don't clutter the rest of your Drive.

## Cell 4 (markdown) — download PTB-XL from PhysioNet

Explains that PTB-XL is downloaded once into Drive specifically so re-running
this notebook later doesn't re-download the ~3GB dataset every time.

## Cell 5 (code) — download (skip if cached)

```python
PTBXL_ROOT = os.path.join(DRIVE_WORKDIR, "ptb-xl-1.0.3")

if not os.path.exists(os.path.join(PTBXL_ROOT, "ptbxl_database.csv")):
    !wget -q -r -N -c -np -P /content/ptbxl_download https://physionet.org/files/ptb-xl/1.0.3/
    downloaded_root = "/content/ptbxl_download/physionet.org/files/ptb-xl/1.0.3"
    !cp -r {downloaded_root} {PTBXL_ROOT}
else:
    print("Already downloaded to Drive, skipping.")

print("PTB-XL root:", PTBXL_ROOT)
assert os.path.exists(os.path.join(PTBXL_ROOT, "ptbxl_database.csv")), "Download failed - check the wget output above."
```

**What/why:** The `if not os.path.exists(...)` guard is a manual caching
layer — since there's no Kaggle "Add Data" step here, this cell has to do the
equivalent work itself, and it checks Drive first so a second run of this
notebook (in a fresh, disconnected Colab session) doesn't re-download several
gigabytes it already has. The `wget` flags matter: `-r` (recursive) and `-np`
(no-parent) follow PhysioNet's directory listing without wandering outside the
`ptb-xl/1.0.3/` folder; `-N` (timestamping) and `-c` (continue) make the
download resumable if it's interrupted partway through — genuinely useful
given Colab's idle-disconnect risk during a multi-gigabyte download.
`wget` naturally recreates PhysioNet's own URL path structure locally
(`physionet.org/files/ptb-xl/1.0.3/...`), which is why the `cp -r` step exists —
it flattens that nested structure into the clean `PTBXL_ROOT` path the rest of
the notebook expects, matching the Kaggle version's `PTBXL_ROOT` variable
exactly so every downstream cell is unchanged. The final `assert` is a fail-fast
check: better to stop here with a clear message than have a confusing
`FileNotFoundError` three cells later if the download silently failed.

## Cells 6–11 — imports, labels, splits, Dataset, model, loss

**Identical to the Kaggle notebook's cells 3, 4, 5, 6, 7, 8, 9** — same
imports and seeding, same SCP-code-to-superclass mapping, same official
`strat_fold` split discipline, same per-lead-normalized `PTBXLDataset`, same
`ECGResNet1D` architecture, same weighted-BCE loss and `AdamW`/cosine-schedule
setup. See
[../kaggle/01_ecg_ptbxl_training.explanation.md](../kaggle/01_ecg_ptbxl_training.explanation.md)
cells 3–9 for the full explanation of each — nothing about them changes when
the platform changes.

## Cell 10 (code) — training loop with Drive checkpointing

```python
def macro_auroc(y_true, y_score): ...  # identical to Kaggle

@torch.no_grad()
def evaluate(loader): ...  # identical to Kaggle

CHECKPOINT_PATH = os.path.join(DRIVE_WORKDIR, "ecg_ptbxl_resnet1d_best.pt")
NUM_EPOCHS = 20
best_val_auroc = 0.0

for epoch in range(NUM_EPOCHS):
    model.train()
    running_loss = 0.0
    for signals, labels in train_loader:
        signals, labels = signals.to(DEVICE), labels.to(DEVICE)
        optimizer.zero_grad()
        logits = model(signals)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        running_loss += loss.item() * signals.size(0)
    scheduler.step()

    train_loss = running_loss / len(train_ds)
    val_auroc, _, _ = evaluate(val_loader)
    print(f"epoch {epoch+1:02d}  train_loss={train_loss:.4f}  val_macro_auroc={val_auroc:.4f}")

    if val_auroc > best_val_auroc:
        best_val_auroc = val_auroc
        torch.save(model.state_dict(), CHECKPOINT_PATH)  # write straight to Drive

model.load_state_dict(torch.load(CHECKPOINT_PATH))
print("Best val macro-AUROC:", best_val_auroc)
```

**What/why — the one meaningful change from Kaggle's training loop:** the
Kaggle version keeps the best checkpoint **in memory** (`best_state_dict =
{...}`, a Python dict of cloned tensors) and only writes to disk once, at the
very end. This Colab version instead calls `torch.save(model.state_dict(),
CHECKPOINT_PATH)` **immediately, every time validation AUROC improves**,
writing straight to the Drive-mounted path. The trade-off: slightly more disk
I/O during training, in exchange for a real guarantee — if Colab disconnects
you mid-run at epoch 15, the epoch-14 checkpoint (or whichever was best so
far) is already sitting safely in your Drive, not lost with the rest of the
session's in-memory state. This is the single most important adaptation in
the whole notebook: it's what makes "train on free-tier Colab, which can
disconnect on you" a workable proposition rather than a gamble on an
uninterrupted 12-hour session.

## Cell 11 (code) — held-out test evaluation

Identical to the Kaggle notebook's cell 10 — same macro-AUROC-per-class
reporting, same manually-computed MI sensitivity at a 0.5 threshold, same
test-fold discipline (touched only here, exactly once).

## Cell 12 (code) — save metadata sidecar

```python
metadata = {
    "model": "ECGResNet1D",
    "superclasses": SUPERCLASSES,
    "sampling_rate_hz": 100,
    "input_shape": [12, 1000],
    "test_macro_auroc": test_auroc,
    "mi_sensitivity_at_0.5": float(mi_sensitivity),
    "trained_on": "PTB-XL, official strat_fold split (train 1-8, val 9, test 10)",
    "trained_on_platform": "Google Colab",
}
with open(os.path.join(DRIVE_WORKDIR, "ecg_ptbxl_resnet1d_best.json"), "w") as handle:
    json.dump(metadata, handle, indent=2)

print("Checkpoint + metadata saved under:", DRIVE_WORKDIR)
print(json.dumps(metadata, indent=2))
```

**What/why:** Same metadata sidecar pattern as the Kaggle notebook, with one
addition worth noticing: `"trained_on_platform": "Google Colab"`. This is a
small but genuinely useful detail for a model registry entry
(`docs/10-observability-mlops.md`) — if a Kaggle-trained and a Colab-trained
checkpoint for the same architecture ever need comparing (e.g., debugging a
performance discrepancy), knowing which ran where narrows down what could
differ (different GPU generation, different exact package versions from each
platform's base image) without having to guess.

## Cell 13 (markdown) — next steps

Points back to the Kaggle notebook's final cell for the full list — subgroup
breakdown, calibration, serving behind a `SpecialistPort` adapter — since none
of that changes based on which platform trained the checkpoint.

## Final summary

The lesson worth carrying forward from this specific port: when adapting a
notebook to a platform with less reliable session persistence, the two things
to change are **where data comes from** and **how often you checkpoint to
somewhere durable** — the model, the math, and the evaluation discipline don't
need to change at all.
