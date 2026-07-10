# 01_ecg_ptbxl_training.ipynb — explained cell by cell

Companion to [01_ecg_ptbxl_training.ipynb](01_ecg_ptbxl_training.ipynb). This is
the **one component in the whole plan trained from scratch**
([docs/12-training-plan.md](../../docs/12-training-plan.md), Vertical 3) — no
credible pretrained 12-lead ECG foundation model exists on Hugging Face today,
so unlike every other notebook in this repo, there's no shortcut here: a real
1D-CNN gets trained on real ECG waveforms.

## How to read this file

Each section below shows the notebook cell's exact code, then explains **what
it does, why it's written this way, and what would go wrong if you changed it**
— not a restatement of the code in English, but the reasoning behind it.

---

## Cell 1 (markdown) — overview

The notebook's intro cell. States the five things this notebook does (load
official folds, map labels, train, evaluate with two separate metrics, save a
checkpoint) and the Kaggle setup steps (add a PTB-XL dataset, GPU accelerator,
Internet on). Nothing to explain mechanically — it's the map for everything below.

## Cell 2 (code) — install dependencies

```python
!pip install -q wfdb neurokit2
```

**What/why:** Kaggle's base image ships PyTorch, NumPy, pandas, and scikit-learn,
but not domain-specific packages. `wfdb` (WaveForm DataBase) is the reference
Python library for reading PhysioNet's raw ECG signal format — without it,
you'd be parsing PTB-XL's binary `.dat`/header `.hea` files by hand. `neurokit2`
is installed but not used directly in this notebook's training loop; it's here
because `docs/12` calls out **NeuroKit2 for R-peak/beat-segmentation features**
as an optional engineered-feature companion to the raw-signal model — if you
later want to add hand-crafted features (heart rate variability, QRS duration)
alongside the CNN's learned features, this is where you'd reach for it. The
`-q` flag just suppresses pip's install log noise.

## Cell 3 (code) — imports and reproducibility

```python
import glob, json, os, random
import numpy as np, pandas as pd, torch, torch.nn as nn, wfdb
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Dataset

SEED = 42
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", DEVICE)
```

**What/why:** Three separate `seed()` calls, not one — Python's `random`,
NumPy's RNG, and PyTorch's RNG are three independent random number generators;
seeding only one leaves the others non-deterministic. This matters because
`docs/12`'s cross-cutting principle 5 requires every training run to be
reproducible and logged (config hash, seed, resulting checkpoint) — without all
three seeds fixed, re-running this notebook wouldn't produce a comparable
result, which breaks the ability to tell whether a later change actually helped.
`DEVICE` is computed once and reused everywhere (`.to(DEVICE)`) rather than
hardcoding `"cuda"`, so the notebook degrades gracefully (slowly, but doesn't
crash) if you accidentally run it without a GPU attached.

## Cell 4 (markdown) — locate the dataset

Explains that different Kaggle PTB-XL mirrors unpack to different folder
layouts, so the next cell searches rather than hardcodes a path.

## Cell 5 (code) — auto-detect the PTB-XL root

```python
candidates = glob.glob("/kaggle/input/**/ptbxl_database.csv", recursive=True)
if not candidates:
    raise FileNotFoundError(
        "Could not find ptbxl_database.csv under /kaggle/input. "
        "Add a PTB-XL dataset via 'Add Data', or set PTBXL_ROOT manually below."
    )
PTBXL_ROOT = os.path.dirname(candidates[0])
print("PTB-XL root:", PTBXL_ROOT)
```

**What/why:** `ptbxl_database.csv` is the one filename every PTB-XL mirror ships
regardless of how the surrounding folders are named, so it's the reliable
anchor to search for. `recursive=True` with the `**` glob pattern walks every
subdirectory under `/kaggle/input` — necessary because Kaggle mounts each
attached dataset under its own auto-generated folder name, which you don't
control. The explicit `raise FileNotFoundError` with an actionable message is
deliberate: a silent `None` or an empty-dataframe failure three cells later
would be much harder to debug than a clear error right where the actual problem
is (no dataset attached).

## Cell 6 (markdown) — build multi-label superclass targets

Explains that `scp_codes` is a dict of diagnostic codes → confidence per record,
and that `scp_statements.csv` maps each code to one of 5 superclasses — a
record can land in more than one, making this a multi-label problem, not a
single-label one.

## Cell 7 (code) — metadata + label mapping

```python
SUPERCLASSES = ["NORM", "MI", "STTC", "CD", "HYP"]

ptbxl_df = pd.read_csv(os.path.join(PTBXL_ROOT, "ptbxl_database.csv"), index_col="ecg_id")
ptbxl_df.scp_codes = ptbxl_df.scp_codes.apply(lambda x: eval(x))  # stored as a string-repr dict

scp_df = pd.read_csv(os.path.join(PTBXL_ROOT, "scp_statements.csv"), index_col=0)
scp_df = scp_df[scp_df.diagnostic == 1]  # only diagnostic statements map to a superclass


def scp_codes_to_superclasses(scp_codes: dict) -> list[str]:
    labels = set()
    for code in scp_codes.keys():
        if code in scp_df.index:
            labels.add(scp_df.loc[code].diagnostic_class)
    return sorted(labels & set(SUPERCLASSES))


ptbxl_df["superclasses"] = ptbxl_df.scp_codes.apply(scp_codes_to_superclasses)
ptbxl_df = ptbxl_df[ptbxl_df.superclasses.apply(len) > 0]  # drop records with no mapped diagnosis

for superclass in SUPERCLASSES:
    ptbxl_df[superclass] = ptbxl_df.superclasses.apply(lambda labels: int(superclass in labels))

print(ptbxl_df[SUPERCLASSES].sum())
```

**What/why:** `eval(x)` on the `scp_codes` column is doing something specific —
PTB-XL ships this column as a Python-dict-literal *string* (e.g.
`"{'NORM': 100.0}"`), not real JSON, so `eval` is the pragmatic (if normally
risky) way to parse it back into an actual dict — safe here only because the
data is a trusted, static CSV you control, not user input. `scp_df.diagnostic
== 1` filters `scp_statements.csv` down to rows that are genuinely diagnostic
statements (PTB-XL also has form and rhythm statement categories that don't map
to a superclass) — skip this filter and you'd get `KeyError`-adjacent noise
from codes with no `diagnostic_class`. The `labels & set(SUPERCLASSES)`
intersection is a safety net: it guarantees the function never returns a label
outside the 5 we're training on, even if `scp_statements.csv` contains other
category values. Dropping records with zero mapped superclasses
(`superclasses.apply(len) > 0`) matters because those records would otherwise
train the model against an all-zero label vector, which is a real label
(technically representing an "unmapped diagnosis") but not one you want the
model equating with these 5 specific outcomes. The final loop turns the
`superclasses` list column into 5 separate `0`/`1` int columns — one per
class — because PyTorch's loss functions want a flat numeric tensor, not a
column of Python lists.

## Cell 8 (markdown) — use the official folds, do not re-split

Explains PTB-XL's `strat_fold` column (1–10) is the dataset authors' own
patient-disjoint stratified split, with the standard convention fold 10 = test,
fold 9 = val, folds 1–8 = train.

## Cell 9 (code) — apply the official split

```python
train_df = ptbxl_df[ptbxl_df.strat_fold <= 8]
val_df = ptbxl_df[ptbxl_df.strat_fold == 9]
test_df = ptbxl_df[ptbxl_df.strat_fold == 10]
print(f"train={len(train_df)} val={len(val_df)} test={len(test_df)}")
```

**What/why:** This looks trivially simple, but it's arguably the single most
important cell in the notebook for scientific validity. `docs/12`'s
cross-cutting principle 1 calls patient-level leakage "the single most common
medical-ML leakage bug" — if you instead did a random 80/10/10 split here, the
same patient's two ECGs could land in both train and test, and the model could
learn to recognize *that patient's heart* rather than the diagnostic pattern,
inflating your test AUROC in a way that won't generalize. `strat_fold` was
built by PTB-XL's authors specifically to avoid this and to keep class
prevalence balanced across folds — reusing it exactly (not `sklearn.
train_test_split`) is also what makes your macro-AUROC comparable to published
PTB-XL leaderboard numbers.

## Cell 10 (markdown) — dataset & preprocessing

Explains the choice of the 100Hz release over 500Hz (faster, sufficient for
5-superclass classification) and per-lead z-normalization.

## Cell 11 (code) — Dataset class

```python
class PTBXLDataset(Dataset):
    def __init__(self, dataframe: pd.DataFrame, root: str):
        self.dataframe = dataframe.reset_index()
        self.root = root

    def __len__(self) -> int:
        return len(self.dataframe)

    def __getitem__(self, index: int):
        row = self.dataframe.iloc[index]
        record_path = os.path.join(self.root, row.filename_lr)
        signal, _ = wfdb.rdsamp(record_path)  # shape: (1000 samples, 12 leads) at 100Hz
        signal = signal.T.astype("float32")  # -> (12, 1000)

        mean = signal.mean(axis=1, keepdims=True)
        std = signal.std(axis=1, keepdims=True) + 1e-6
        signal = (signal - mean) / std

        labels = row[SUPERCLASSES].values.astype("float32")
        return torch.from_numpy(signal), torch.from_numpy(labels)


train_ds = PTBXLDataset(train_df, PTBXL_ROOT)
val_ds = PTBXLDataset(val_df, PTBXL_ROOT)
test_ds = PTBXLDataset(test_df, PTBXL_ROOT)

train_loader = DataLoader(train_ds, batch_size=128, shuffle=True, num_workers=2, drop_last=True)
val_loader = DataLoader(val_ds, batch_size=256, shuffle=False, num_workers=2)
test_loader = DataLoader(test_ds, batch_size=256, shuffle=False, num_workers=2)
```

**What/why:** `wfdb.rdsamp` returns `(samples, leads)` — i.e. time first,
channels second — but PyTorch's 1D convolutions expect `(channels, time)`, so
`.T` transposes it. The per-lead normalization (`mean`/`std` computed with
`axis=1`, i.e. across time, separately for each of the 12 leads) matters
because different leads have genuinely different baseline voltage scales; a
single global mean/std across all 12 leads would let high-amplitude leads
dominate the loss simply due to scale, not clinical significance. The `+ 1e-6`
on `std` is a numerical-stability guard against a flat-line lead dividing by
zero. `shuffle=True` + `drop_last=True` on the **training** loader only:
shuffling prevents the model from learning any accidental ordering in the CSV;
dropping the last partial batch keeps `BatchNorm1d` (used in the model below)
from seeing a batch of size 1, which would make its running-statistics update
unstable. Validation/test loaders don't shuffle — order doesn't matter for
evaluation, and keeping it fixed makes debugging easier (same batch = same
error, every run).

## Cell 12 (markdown) — model architecture

Explains the choice: a compact 1D ResNet (strided conv blocks, residual
connections, global average pooling, linear head) — small enough to train from
scratch in hours on one GPU, per `docs/12`'s "1D-CNN or CNN+transformer hybrid."

## Cell 13 (code) — model definition

```python
class ResidualBlock1D(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size=7, stride=stride, padding=3, bias=False)
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size=7, padding=3, bias=False)
        self.bn2 = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = None
        if stride != 1 or in_channels != out_channels:
            self.downsample = nn.Sequential(
                nn.Conv1d(in_channels, out_channels, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm1d(out_channels),
            )

    def forward(self, x):
        identity = x if self.downsample is None else self.downsample(x)
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return self.relu(out + identity)


class ECGResNet1D(nn.Module):
    def __init__(self, in_leads: int = 12, num_classes: int = len(SUPERCLASSES)):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv1d(in_leads, 32, kernel_size=15, stride=2, padding=7, bias=False),
            nn.BatchNorm1d(32),
            nn.ReLU(inplace=True),
        )
        self.layer1 = ResidualBlock1D(32, 64, stride=2)
        self.layer2 = ResidualBlock1D(64, 128, stride=2)
        self.layer3 = ResidualBlock1D(128, 256, stride=2)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Linear(256, num_classes)

    def forward(self, x):
        x = self.stem(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.pool(x).squeeze(-1)
        return self.head(x)


model = ECGResNet1D().to(DEVICE)
print(sum(p.numel() for p in model.parameters()) / 1e6, "M parameters")
```

**What/why:** The `downsample` branch in `ResidualBlock1D` exists because a
residual connection (`out + identity`) requires both tensors to have the same
shape — but every block here changes the channel count (32→64→128→256) *and*
downsamples time via `stride`, so the "identity" path needs its own 1x1 conv +
BatchNorm to match. Without it, this would just crash on a shape mismatch.
`bias=False` on every conv is standard practice when a `BatchNorm1d`
immediately follows — BatchNorm's own learned shift makes the convolution's
bias term redundant, so it's dropped to save (a small amount of) memory. Each
stage halves the number of samples (stride=2, four times total: stem +
3 layers → 1000 samples becomes ~62), while quadrupling then some the channel
depth — this is the standard CNN trade-off of trading spatial/temporal
resolution for richer per-position features as you go deeper.
`AdaptiveAvgPool1d(1)` collapses whatever time dimension is left into a single
value per channel, which is what makes the final `Linear(256, 5)` head
independent of the exact input length — useful if you ever feed it a
differently-sampled signal. The parameter count print is a quick sanity check:
if this were unexpectedly in the hundreds of millions, that would signal a
config mistake before you burn GPU hours training it.

## Cell 14 (markdown) — loss: weighted multi-label BCE

Explains why plain BCE would be wrong here: MI-related labels are much rarer
than "normal," so per-class positive weights are needed.

## Cell 15 (code) — imbalance-aware loss + optimizer

```python
positive_counts = train_df[SUPERCLASSES].sum().values
negative_counts = len(train_df) - positive_counts
pos_weight = torch.tensor(negative_counts / np.clip(positive_counts, 1, None), dtype=torch.float32).to(DEVICE)
print("pos_weight per class:", dict(zip(SUPERCLASSES, pos_weight.tolist())))

criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=20)
```

**What/why:** `pos_weight` in `BCEWithLogitsLoss` scales the loss contribution
of *positive* examples for each class independently — a class with 10x fewer
positives than negatives gets `pos_weight ≈ 10`, meaning the model is punished
10x harder for missing a positive of that class than for missing a negative.
Without this, a model that just predicts "not MI" for everyone would still
score deceptively low loss, since MI is a minority class. `np.clip(...,  1,
None)` guards against division-by-zero if a class happened to have zero
training positives (shouldn't happen with all 5 superclasses, but it's a cheap
safety net). `BCEWithLogitsLoss` specifically (not plain `BCELoss` after a
manual sigmoid) is used because it combines the sigmoid and the loss in one
numerically-stable operation — doing them separately can silently produce
`NaN` losses when logits get large. `AdamW` (not plain `Adam`) decouples weight
decay from the gradient update, which is the now-standard fix for a subtle bug
in how original Adam applied L2 regularization. `CosineAnnealingLR` smoothly
decays the learning rate over the 20 planned epochs, which typically helps the
model settle into a better minimum in its final epochs rather than continuing
to take large, potentially destabilizing steps.

## Cell 16 (markdown) — training loop

Explains that this loop tracks validation macro-AUROC each epoch and keeps the
best checkpoint — a miniature version of the full promotion-gate check
(`docs/12`/`docs/10`) that happens for real outside this notebook.

## Cell 17 (code) — train + validate

```python
def macro_auroc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    scores = []
    for class_index in range(y_true.shape[1]):
        if len(np.unique(y_true[:, class_index])) < 2:
            continue  # AUROC is undefined for a class with only one label value present
        scores.append(roc_auc_score(y_true[:, class_index], y_score[:, class_index]))
    return float(np.mean(scores))


@torch.no_grad()
def evaluate(loader: DataLoader) -> tuple[float, np.ndarray, np.ndarray]:
    model.eval()
    all_true, all_score = [], []
    for signals, labels in loader:
        signals = signals.to(DEVICE)
        logits = model(signals)
        all_true.append(labels.numpy())
        all_score.append(torch.sigmoid(logits).cpu().numpy())
    y_true = np.concatenate(all_true)
    y_score = np.concatenate(all_score)
    return macro_auroc(y_true, y_score), y_true, y_score


NUM_EPOCHS = 20
best_val_auroc = 0.0
best_state_dict = None

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
        best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}

model.load_state_dict(best_state_dict)
print("Best val macro-AUROC:", best_val_auroc)
```

**What/why:** `roc_auc_score` is mathematically undefined when a class has
only one unique label value in the batch being scored (there's no "negative"
to rank against), so `macro_auroc` explicitly skips those classes rather than
letting `sklearn` raise — this matters more on small val/test slices than on
the full test fold. `@torch.no_grad()` on `evaluate` disables gradient tracking
entirely during validation, which both speeds it up and prevents accidentally
leaking validation-time computation into the training graph. `model.eval()`
vs `model.train()` toggles `BatchNorm1d`'s behavior specifically — in eval
mode it uses running statistics accumulated during training instead of the
current batch's statistics, which is what makes validation-time predictions
independent of whatever batch happens to be evaluated alongside them.
`loss.item() * signals.size(0)` then dividing by `len(train_ds)` at the end
computes a properly weighted average loss across batches of potentially
different sizes (the last batch is dropped here, but this pattern is a good
habit generally). The best-checkpoint tracking (`best_state_dict = {...
.cpu().clone() ...}`) explicitly copies to CPU and clones — without `.clone()`,
you'd be holding a reference to tensors that keep changing as training
continues, and you'd end up saving whatever the *final* epoch's weights were,
not the actual best epoch's.

## Cell 18 (markdown) — final evaluation

Explains the two metrics reported: macro-AUROC (the PTB-XL standard) and MI
sensitivity tracked separately, since a missed MI is a different risk tier than
a missed minor finding.

## Cell 19 (code) — held-out test evaluation

```python
test_auroc, y_true, y_score = evaluate(test_loader)
print("Test macro-AUROC:", test_auroc)

for class_index, superclass in enumerate(SUPERCLASSES):
    class_auroc = roc_auc_score(y_true[:, class_index], y_score[:, class_index])
    print(f"  {superclass}: AUROC={class_auroc:.4f}")

mi_index = SUPERCLASSES.index("MI")
mi_predictions = (y_score[:, mi_index] >= 0.5).astype(int)
mi_true_positive = ((mi_predictions == 1) & (y_true[:, mi_index] == 1)).sum()
mi_actual_positive = (y_true[:, mi_index] == 1).sum()
mi_sensitivity = mi_true_positive / max(mi_actual_positive, 1)
print(f"MI sensitivity @0.5 threshold: {mi_sensitivity:.4f}  ({mi_true_positive}/{mi_actual_positive})")
```

**What/why:** This is the **only** place the test fold gets touched in the
whole notebook — everything above uses train/val only, which is exactly the
discipline that makes the resulting number trustworthy (a model that had
"peeked" at test data during development would score better here for the wrong
reasons). Sensitivity (true positive rate) is computed manually here rather
than via a library helper, at a fixed 0.5 threshold, specifically for MI — this
directly implements `docs/12`'s instruction to track a clinically critical
class's miss rate *separately* from the aggregate AUROC, since averaging it
into the macro score would let strong performance on `NORM` (the majority
class) mask a real weakness on MI.

## Cell 20 (markdown) — save the checkpoint

Explains the `.pt` file is a portable `state_dict`, and that it must be
DVC-tracked (never git-committed) and go through the model registry in
`shadow` status before serving real traffic.

## Cell 21 (code) — save checkpoint + metadata

```python
checkpoint_path = "/kaggle/working/ecg_ptbxl_resnet1d.pt"
torch.save(model.state_dict(), checkpoint_path)

metadata = {
    "model": "ECGResNet1D",
    "superclasses": SUPERCLASSES,
    "sampling_rate_hz": 100,
    "input_shape": [12, 1000],
    "test_macro_auroc": test_auroc,
    "mi_sensitivity_at_0.5": float(mi_sensitivity),
    "trained_on": "PTB-XL, official strat_fold split (train 1-8, val 9, test 10)",
}
with open("/kaggle/working/ecg_ptbxl_resnet1d.json", "w") as handle:
    json.dump(metadata, handle, indent=2)

print("Saved:", checkpoint_path)
print(json.dumps(metadata, indent=2))
```

**What/why:** `torch.save(model.state_dict(), ...)` saves only the learned
weights, not the full model object — the more portable choice, since it
doesn't pickle Python class internals that could break across PyTorch versions
or refactors; the cost is that whoever loads it must re-declare an identical
`ECGResNet1D` class first. The `.json` metadata sidecar isn't optional
decoration — it's what a model registry entry (`docs/10-observability-mlops.md`)
actually needs to record: which architecture, what input shape it expects,
what its measured performance was, and exactly what data/split it was trained
against, so a reviewer six months from now doesn't have to reverse-engineer
those facts from the notebook.

## Cell 22 (markdown) — next steps

Lists what still has to happen *outside* this notebook before this checkpoint
is production-eligible: download it, run the subgroup breakdown (age/sex/site),
fit post-hoc calibration, then serve it behind an HTTP endpoint and point an
ECG `SpecialistPort` adapter's `endpoint_url` at it — reusing the exact pattern
`ModelBackedChestXRaySpecialistAdapter` already implements in the main codebase.

## Final summary

The backbone pattern here — locate/validate data, build labels off official
metadata, split by the dataset's own predefined folds, normalize per-instance,
train with an imbalance-aware loss while tracking the *right* validation metric,
evaluate once on a held-out set, save weights + metadata together — is the same
skeleton every notebook in this repo follows. What changes per vertical is the
data shape (waveforms here, images or video elsewhere) and which metric matters
most for that clinical task.
