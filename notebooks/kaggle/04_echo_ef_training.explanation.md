# 04_echo_ef_training.ipynb — explained cell by cell

Companion to [04_echo_ef_training.ipynb](04_echo_ef_training.ipynb). Per
[docs/04-data-models.md](../../docs/04-data-models.md), no verified
Echo-Vision-FM-class checkpoint existed on Hugging Face at planning time —
**re-check before running this**, since that's exactly the kind of thing that
changes fast. If nothing suitable turns up, this notebook trains a compact
video model on EchoNet-Dynamic to predict **ejection fraction (EF)**, the
percentage of blood the left ventricle pumps out with each heartbeat.

## How to read this file

Each cell's code is shown exactly as it appears in the notebook, followed by an
explanation of the mechanics and the reasoning.

---

## Cell 1 (markdown) — overview

States the four things this notebook does: load `FileList.csv` and the
official split, sample frames per video, train a CNN + temporal pooling model
for EF regression, and evaluate with MAE/R². Notes EchoNet-Dynamic requires a
Stanford data-use agreement officially, though unofficial Kaggle mirrors also
exist for prototyping.

## Cell 2 (code) — install dependencies

```python
!pip install -q opencv-python-headless
```

**What/why:** `opencv-python-headless` is the variant of OpenCV without GUI
bindings (no `cv2.imshow` support) — the right choice for a server/notebook
environment like Kaggle that has no display, and it avoids pulling in GUI
system libraries the regular `opencv-python` package would need. This is
usually a no-op since Kaggle's base image often has some form of OpenCV
preinstalled already; the `pip install` just ensures the specific package is
present.

## Cell 3 (code) — imports and reproducibility

```python
import glob, json, os, random
import cv2, numpy as np, pandas as pd, torch, torch.nn as nn
import torchvision.models as tv_models
from sklearn.metrics import mean_absolute_error, r2_score
from torch.utils.data import DataLoader, Dataset

SEED = 42
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", DEVICE)
```

**What/why:** Same three-RNG reproducibility pattern as every other notebook.
`torchvision.models` is imported specifically for its pretrained ResNet18 —
used as the per-frame encoder in the model cell below, the one piece of this
notebook that reuses a pretrained backbone rather than training from
scratch end-to-end.

## Cell 4 (code) — locate the dataset

```python
candidates = glob.glob("/kaggle/input/**/FileList.csv", recursive=True)
if not candidates:
    raise FileNotFoundError(
        "Could not find FileList.csv under /kaggle/input. "
        "Add an EchoNet-Dynamic dataset via 'Add Data', or set ECHONET_ROOT manually."
    )
ECHONET_ROOT = os.path.dirname(candidates[0])
VIDEOS_DIR = os.path.join(ECHONET_ROOT, "Videos")
if not os.path.isdir(VIDEOS_DIR):
    nested = glob.glob(os.path.join(ECHONET_ROOT, "**", "Videos"), recursive=True)
    VIDEOS_DIR = nested[0] if nested else VIDEOS_DIR
print("EchoNet root:", ECHONET_ROOT)
print("Videos dir:", VIDEOS_DIR)
```

**What/why:** Same "search for the one distinctive filename" pattern used for
PTB-XL and BraTS — `FileList.csv` is the anchor file every EchoNet-Dynamic
mirror ships. The extra fallback (`nested = glob.glob(...  "Videos"...)`)
exists because some mirrors put `Videos/` directly next to `FileList.csv` while
others nest it one level deeper — rather than failing on a mirror-specific
quirk, this cell tries the direct path first and only searches further if that
guess is wrong.

## Cell 5 (code) — load metadata and the official split

```python
file_list = pd.read_csv(os.path.join(ECHONET_ROOT, "FileList.csv"))
print(file_list[["FileName", "EF", "Split"]].head())
print(file_list.Split.value_counts())

train_df = file_list[file_list.Split == "TRAIN"].reset_index(drop=True)
val_df = file_list[file_list.Split == "VAL"].reset_index(drop=True)
test_df = file_list[file_list.Split == "TEST"].reset_index(drop=True)
print(f"train={len(train_df)} val={len(val_df)} test={len(test_df)}")
```

**What/why:** `FileList.csv`'s `Split` column (`TRAIN`/`VAL`/`TEST`) is
EchoNet-Dynamic's own author-assigned split, analogous to PTB-XL's
`strat_fold` and BraTS's leaderboard/training separation — using it as-is
(rather than a fresh random split) is the same "use the official split"
discipline `docs/12` applies everywhere, and it's what keeps your MAE
comparable to published EchoNet benchmarks.

## Cell 6 (markdown) — frame sampling

Explains the compute trade-off: evenly-spaced frame sampling covers at least
one cardiac cycle per clip while staying far cheaper than full-framerate 3D
convolution over the whole video — the same "patch/embedding over full-volume"
principle used for BraTS and CT-FM, applied along the time axis instead of space.

## Cell 7 (code) — Dataset class

```python
NUM_FRAMES = 16
FRAME_SIZE = 112


def read_sampled_frames(video_path: str, num_frames: int, frame_size: int) -> np.ndarray:
    capture = cv2.VideoCapture(video_path)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_indices = np.linspace(0, max(total_frames - 1, 0), num_frames).astype(int)

    frames = []
    for target_index in frame_indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(target_index))
        success, frame = capture.read()
        if not success:
            frame = np.zeros((frame_size, frame_size, 3), dtype=np.uint8)
        else:
            frame = cv2.resize(frame, (frame_size, frame_size))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(frame)
    capture.release()

    clip = np.stack(frames).astype("float32") / 255.0  # (T, H, W, C)
    clip = (clip - 0.5) / 0.5
    return clip.transpose(3, 0, 1, 2)  # -> (C, T, H, W)


class EchoNetDataset(Dataset):
    def __init__(self, dataframe: pd.DataFrame, videos_dir: str):
        self.dataframe = dataframe
        self.videos_dir = videos_dir

    def __len__(self) -> int:
        return len(self.dataframe)

    def __getitem__(self, index: int):
        row = self.dataframe.iloc[index]
        filename = row.FileName if row.FileName.endswith(".avi") else f"{row.FileName}.avi"
        video_path = os.path.join(self.videos_dir, filename)
        clip = read_sampled_frames(video_path, NUM_FRAMES, FRAME_SIZE)
        ejection_fraction = np.float32(row.EF) / 100.0  # normalize EF% to [0, 1] for stable regression
        return torch.from_numpy(clip), torch.tensor(ejection_fraction)


train_ds = EchoNetDataset(train_df, VIDEOS_DIR)
val_ds = EchoNetDataset(val_df, VIDEOS_DIR)
test_ds = EchoNetDataset(test_df, VIDEOS_DIR)

train_loader = DataLoader(train_ds, batch_size=8, shuffle=True, num_workers=2, drop_last=True)
val_loader = DataLoader(val_ds, batch_size=8, shuffle=False, num_workers=2)
test_loader = DataLoader(test_ds, batch_size=8, shuffle=False, num_workers=2)
```

**What/why:** `np.linspace(0, total_frames - 1, num_frames)` picks 16 frame
indices **evenly spaced across the entire clip's duration**, not the first 16
frames — this matters because a cardiac cycle (one full heartbeat's worth of
contraction and relaxation, which is what EF actually measures) spans the
whole clip, not just its beginning. The `if not success: frame = np.zeros(...)`
fallback handles a real edge case in encoded video files: a requested frame
index occasionally fails to decode (corrupt frame, container quirk), and a
black placeholder frame is a safer failure mode than crashing the whole
data-loading pipeline partway through training. `.astype("float32") / 255.0`
then `(clip - 0.5) / 0.5` rescales pixel values from `[0, 255]` to `[-1, 1]` —
a common normalization range for CNNs, distinct from the mean/std
normalization used in the ECG notebook because here it's simple min-max
rescaling, not per-channel statistical normalization. `clip.transpose(3, 0, 1,
2)` reorders from `(T, H, W, C)` (OpenCV's natural output order) to `(C, T, H,
W)`, matching what the model consumes below. Normalizing `EF` to `[0, 1]` (by
dividing by 100) is done specifically because the model ends in a `Sigmoid`
(cell 8) — sigmoid naturally outputs `[0, 1]`, so scaling the target to match
keeps the regression numerically well-behaved; the loop later multiplies
predictions back by 100 whenever it reports a human-readable EF percentage.

## Cell 8 (markdown) — model architecture

Explains the two-stage design: a per-frame CNN encoder (ResNet18) followed by
temporal attention pooling across frames — the same attention-pooling idea as
the pathology notebook's MIL aggregator, applied along time instead of across
patches.

## Cell 9 (code) — model definition

```python
class EchoEFRegressor(nn.Module):
    def __init__(self):
        super().__init__()
        backbone = tv_models.resnet18(weights=tv_models.ResNet18_Weights.IMAGENET1K_V1)
        backbone.fc = nn.Identity()
        self.frame_encoder = backbone
        self.frame_feature_dim = 512

        self.temporal_attention = nn.Sequential(
            nn.Linear(self.frame_feature_dim, 128),
            nn.Tanh(),
            nn.Linear(128, 1),
        )
        self.regression_head = nn.Sequential(
            nn.Linear(self.frame_feature_dim, 64),
            nn.ReLU(inplace=True),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )

    def forward(self, clip: torch.Tensor) -> torch.Tensor:
        batch_size, channels, num_frames, height, width = clip.shape
        frames = clip.permute(0, 2, 1, 3, 4).reshape(batch_size * num_frames, channels, height, width)
        frame_features = self.frame_encoder(frames).view(batch_size, num_frames, self.frame_feature_dim)

        attention_logits = self.temporal_attention(frame_features).squeeze(-1)
        attention_weights = torch.softmax(attention_logits, dim=1).unsqueeze(-1)
        pooled_features = (attention_weights * frame_features).sum(dim=1)

        return self.regression_head(pooled_features).squeeze(-1)


model = EchoEFRegressor().to(DEVICE)
print(sum(p.numel() for p in model.parameters()) / 1e6, "M parameters")
```

**What/why:** `backbone.fc = nn.Identity()` is the standard trick for reusing a
classification backbone as a feature extractor — ResNet18's final layer
normally maps its 512-dim pooled features to 1000 ImageNet classes;
replacing it with a no-op lets `frame_encoder(frames)` return the raw 512-dim
feature vector instead. This backbone is **fine-tuned end-to-end** (unlike the
pathology notebook's frozen ViT) because echo ultrasound frames look
substantially different from natural photos — the notebook's own note explains
this modality shift is large enough that full fine-tuning converges better
than treating ImageNet features as fixed. `clip.permute(0, 2, 1, 3, 4).reshape(
batch_size * num_frames, channels, height, width)` is doing real work: it
folds the time dimension into the batch dimension so all frames from all clips
in the batch get encoded in **one** forward pass through the 2D CNN (which
only understands `(batch, C, H, W)`), rather than looping frame-by-frame in
Python — then `.view(batch_size, num_frames, ...)` unfolds it back afterward.
The temporal attention block is structurally identical to the pathology
notebook's `AttentionMIL` (`Linear → Tanh → Linear`, then softmax-normalized
weights, then a weighted sum) — same underlying idea, applied here across
**frames of one clip** instead of across **patches of one bag**. The final
`Sigmoid` is what makes the `[0, 1]`-normalized EF target from cell 7 the
correct choice — the network's output range and the label's range have to
match for the loss to be meaningful.

## Cell 10 (markdown) — training loop

Explains the loss choice: MAE directly on normalized EF, equivalent to MAE in
EF-percentage terms after multiplying back by 100.

## Cell 11 (code) — train + validate

```python
criterion = nn.L1Loss()
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-5)


@torch.no_grad()
def evaluate(loader: DataLoader) -> tuple[float, float]:
    model.eval()
    all_true, all_pred = [], []
    for clips, ef_true in loader:
        clips = clips.to(DEVICE)
        ef_pred = model(clips).cpu()
        all_true.append(ef_true * 100.0)
        all_pred.append(ef_pred * 100.0)
    y_true = torch.cat(all_true).numpy()
    y_pred = torch.cat(all_pred).numpy()
    return mean_absolute_error(y_true, y_pred), r2_score(y_true, y_pred)


NUM_EPOCHS = 10
best_val_mae = float("inf")
best_state_dict = None

for epoch in range(NUM_EPOCHS):
    model.train()
    running_loss = 0.0
    for clips, ef_true in train_loader:
        clips, ef_true = clips.to(DEVICE), ef_true.to(DEVICE)
        optimizer.zero_grad()
        ef_pred = model(clips)
        loss = criterion(ef_pred, ef_true)
        loss.backward()
        optimizer.step()
        running_loss += loss.item() * clips.size(0)

    train_loss = running_loss / len(train_ds)
    val_mae, val_r2 = evaluate(val_loader)
    print(f"epoch {epoch+1:02d}  train_mae_norm={train_loss:.4f}  val_EF_MAE={val_mae:.2f}  val_R2={val_r2:.4f}")

    if val_mae < best_val_mae:
        best_val_mae = val_mae
        best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}

model.load_state_dict(best_state_dict)
print("Best val EF MAE:", best_val_mae)
```

**What/why:** `nn.L1Loss()` is PyTorch's mean-absolute-error loss — chosen
over MSE (`nn.MSELoss`) because MAE weighs all errors linearly, while MSE
squares them and so penalizes a few large errors much more heavily; MAE is
also the metric EchoNet-Dynamic's own benchmark reports, so training against
it directly (rather than a proxy loss) keeps the optimization target aligned
with the evaluation target. The `best_val_mae` tracking uses `<` (lower is
better) rather than the `>` seen in the AUROC-tracking notebooks, since this is
an error metric, not a discrimination score — a detail easy to get backwards
if you're copying this pattern into a new notebook. `all_true.append(ef_true *
100.0)` inside `evaluate` is where the `[0, 1]`-normalized values from cell 7
get converted back to real EF percentages purely for reporting — the model
itself trains and predicts entirely in normalized space; only the printed/
returned metrics are in human-readable percentage-point units.

## Cell 12 (code) — held-out test evaluation

```python
test_mae, test_r2 = evaluate(test_loader)
print(f"Test EF MAE: {test_mae:.2f} percentage points")
print(f"Test R^2: {test_r2:.4f}")
```

**What/why:** Two complementary metrics: MAE gives an absolute, clinically
interpretable number ("the model is off by X percentage points of EF on
average"), while R² gives a relative sense of how much of the patient-to-patient
EF variance the model actually explains versus just predicting the mean EF for
everyone — a model could have deceptively "reasonable" MAE while still having
near-zero R² if the dataset's EF values cluster tightly together, so reporting
both avoids being misled by either one alone.

## Cell 13 (code) — save the checkpoint

```python
checkpoint_path = "/kaggle/working/echonet_ef_regressor.pt"
torch.save(model.state_dict(), checkpoint_path)

metadata = {
    "model": "EchoEFRegressor",
    "num_frames_sampled": NUM_FRAMES,
    "frame_size": FRAME_SIZE,
    "test_ef_mae": float(test_mae),
    "test_r2": float(test_r2),
    "trained_on": "EchoNet-Dynamic, official FileList.csv Split column",
}
with open("/kaggle/working/echonet_ef_regressor.json", "w") as handle:
    json.dump(metadata, handle, indent=2)

print("Saved:", checkpoint_path)
print(json.dumps(metadata, indent=2))
```

**What/why:** Same pattern as every other notebook: plain `state_dict` (not
the full pickled model object) plus a metadata sidecar that records exactly
what would otherwise have to be reverse-engineered from the notebook later —
frame sampling parameters (`num_frames_sampled`, `frame_size`) matter here
specifically because they're required at *inference* time too; feeding this
model a differently-sampled clip than it was trained on would silently degrade
predictions rather than raising an error.

## Cell 14 (markdown) — next steps

Flags four things outside this notebook's scope: re-checking Hugging Face for
an Echo-Vision-FM checkpoint before committing further to training from
scratch; that this notebook only does EF regression, not the wall-motion
classification `docs/12` also lists for this vertical; the standard subgroup
breakdown/calibration/registry steps; and switching from an unofficial Kaggle
mirror to the official Stanford release before anything beyond prototyping.

## Final summary

This notebook's core trick — encode each frame independently with a 2D CNN,
then use learned attention to pool across the time dimension instead of hand-picking
"the most important frame" — is a general pattern for any per-clip
prediction task where full 3D video convolution would be too expensive. The
same attention-pooling shape shows up in the pathology notebook applied to
patches instead of frames; recognizing that structural similarity is more
useful long-term than memorizing either notebook's specific code.
