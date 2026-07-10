# 02_pathology_mil_training.ipynb — explained cell by cell

Companion to [02_pathology_mil_training.ipynb](02_pathology_mil_training.ipynb).
Per [docs/12-training-plan.md](../../docs/12-training-plan.md), this is a
**"light training"** vertical — a strong pretrained vision backbone already
exists, so only the small **MIL (multiple-instance learning) aggregator head**
gets trained; the embedding backbone stays frozen throughout.

## How to read this file

Each cell's code is shown exactly as it appears in the notebook, followed by an
explanation of the mechanics and the reasoning — not a restatement of the code.

---

## Cell 1 (markdown) — overview

Explains the MIL framing: PatchCamelyon patches stand in for real slide
patches (full gigapixel CAMELYON WSIs aren't practical on a single GPU), an
attention-based MIL head learns which patches in a "bag" matter for the
bag-level label, and the resulting attention weights double as a saliency
signal.

## Cell 2 (code) — install dependencies

```python
!pip install -q datasets transformers accelerate
```

**What/why:** `datasets` is Hugging Face's data-loading library — it's what
pulls PatchCamelyon directly from the Hub without you manually downloading and
unzipping anything. `transformers` provides the pretrained vision model and
its matching image preprocessor. `accelerate` is a `transformers` runtime
dependency for device placement; it's not called directly in this notebook but
some model-loading code paths expect it to be importable.

## Cell 3 (code) — imports and reproducibility

```python
import json, random
import numpy as np, torch, torch.nn as nn, torch.nn.functional as F
from datasets import load_dataset
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Dataset
from transformers import AutoImageProcessor, AutoModel

SEED = 42
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", DEVICE)
```

**What/why:** Same three-RNG seeding discipline as every other notebook in this
set (Python, NumPy, PyTorch each have independent state). `AutoImageProcessor`
and `AutoModel` are `transformers`' generic loaders — using the `Auto*` classes
rather than a model-specific class means swapping `EMBED_MODEL_NAME` later
(e.g., to a different vision backbone) doesn't require changing this import.

## Cell 4 (code) — load PatchCamelyon

```python
TRAIN_PATCH_LIMIT = 20_000
VAL_PATCH_LIMIT = 4_000
TEST_PATCH_LIMIT = 4_000

raw_train = load_dataset("dpdl-benchmark/patch_camelyon", split=f"train[:{TRAIN_PATCH_LIMIT}]")
raw_val = load_dataset("dpdl-benchmark/patch_camelyon", split=f"validation[:{VAL_PATCH_LIMIT}]")
raw_test = load_dataset("dpdl-benchmark/patch_camelyon", split=f"test[:{TEST_PATCH_LIMIT}]")
print(raw_train, raw_val, raw_test)
```

**What/why:** The `[:20_000]` slice syntax is Hugging Face `datasets`' split
slicing — it downloads/streams only the first 20,000 examples of the `train`
split rather than the full ~260k-patch dataset. This is a deliberate
Kaggle-session-budget trade-off: the full dataset would make embedding
extraction (the next cells) take much longer for a notebook meant to prove the
pipeline, not chase a leaderboard number. Raise these limits once you have a
longer compute budget and want a stronger result.

## Cell 5 (code) — load the frozen embedding backbone

```python
EMBED_MODEL_NAME = "google/vit-base-patch16-224-in21k"

image_processor = AutoImageProcessor.from_pretrained(EMBED_MODEL_NAME)
embed_model = AutoModel.from_pretrained(EMBED_MODEL_NAME).to(DEVICE).eval()
for parameter in embed_model.parameters():
    parameter.requires_grad_(False)

EMBED_DIM = embed_model.config.hidden_size
print("Embedding dimension:", EMBED_DIM)
```

**What/why:** `requires_grad_(False)` on every parameter is the line that
actually makes this "light training" — it tells PyTorch's autograd not to
compute gradients for the backbone at all, so no matter what happens later,
this model's weights physically cannot change. `.eval()` additionally disables
dropout and switches BatchNorm/LayerNorm to inference-mode statistics, which
matters for getting *consistent* embeddings across calls (an embedding model in
train mode would give slightly different outputs for the same input each time).
The markdown note in the notebook explains why a general ViT is used here
instead of MedGemma directly: MedGemma is built to be queried through its
multimodal chat interface, and reliably extracting clean patch embeddings from
its internals varies by release — `EMBED_DIM` is read from the model's own
config rather than hardcoded, so swapping `EMBED_MODEL_NAME` later doesn't
require hunting down a magic number elsewhere in the notebook.

## Cell 6 (code) — embed every patch once

```python
@torch.no_grad()
def embed_split(raw_split, batch_size: int = 64) -> tuple[torch.Tensor, torch.Tensor]:
    embeddings, labels = [], []
    for start in range(0, len(raw_split), batch_size):
        batch = raw_split[start : start + batch_size]
        pixel_values = image_processor(images=batch["image"], return_tensors="pt").pixel_values.to(DEVICE)
        pooled = embed_model(pixel_values=pixel_values).last_hidden_state[:, 0, :]  # CLS token
        embeddings.append(pooled.cpu())
        labels.extend(batch["label"])
    return torch.cat(embeddings), torch.tensor(labels, dtype=torch.float32)


train_embeddings, train_labels = embed_split(raw_train)
val_embeddings, val_labels = embed_split(raw_val)
test_embeddings, test_labels = embed_split(raw_test)
print(train_embeddings.shape, val_embeddings.shape, test_embeddings.shape)
```

**What/why:** `last_hidden_state[:, 0, :]` — a Vision Transformer processes an
image as a sequence of patch tokens plus one special **CLS token** prepended at
position 0, which the model is pretrained to treat as a summary of the whole
image; indexing `[:, 0, :]` pulls out exactly that summary vector rather than
all the individual patch tokens. `.cpu()` on the result immediately moves each
batch's embeddings off the GPU — necessary because accumulating 20,000+
embeddings directly on GPU memory across the whole loop would risk running out
of VRAM; embeddings are small enough that CPU RAM handles them easily. This is
the single most expensive cell in the notebook (a full forward pass through a
ViT for every patch), which is exactly why it only has to run **once** — every
subsequent cell reuses these cached tensors instead of re-embedding.

## Cell 7 (markdown) — build bags

Explains the MIL framing: bags need one label per group of patches, not per
patch, and that PatchCamelyon only ships patch-level labels, so this notebook
groups patches into synthetic bags as a stand-in — flagging clearly that a
real deployment must group by actual slide ID instead.

## Cell 8 (code) — group embeddings into bags

```python
BAG_SIZE = 20


def make_bags(embeddings: torch.Tensor, labels: torch.Tensor, bag_size: int, seed: int):
    generator = torch.Generator().manual_seed(seed)
    permutation = torch.randperm(len(embeddings), generator=generator)
    bags, bag_labels = [], []
    for start in range(0, len(permutation) - bag_size + 1, bag_size):
        indices = permutation[start : start + bag_size]
        bags.append(embeddings[indices])
        bag_labels.append(float(labels[indices].max()))
    return bags, torch.tensor(bag_labels, dtype=torch.float32)


train_bags, train_bag_labels = make_bags(train_embeddings, train_labels, BAG_SIZE, seed=SEED)
val_bags, val_bag_labels = make_bags(val_embeddings, val_labels, BAG_SIZE, seed=SEED + 1)
test_bags, test_bag_labels = make_bags(test_embeddings, test_labels, BAG_SIZE, seed=SEED + 2)
print(f"bags: train={len(train_bags)} val={len(val_bags)} test={len(test_bags)}")


class BagDataset(Dataset):
    def __init__(self, bags: list[torch.Tensor], bag_labels: torch.Tensor):
        self.bags = bags
        self.bag_labels = bag_labels

    def __len__(self) -> int:
        return len(self.bags)

    def __getitem__(self, index: int):
        return self.bags[index], self.bag_labels[index]


train_loader = DataLoader(BagDataset(train_bags, train_bag_labels), batch_size=1, shuffle=True)
val_loader = DataLoader(BagDataset(val_bags, val_bag_labels), batch_size=1, shuffle=False)
test_loader = DataLoader(BagDataset(test_bags, test_bag_labels), batch_size=1, shuffle=False)
```

**What/why:** `bag_labels.append(float(labels[indices].max()))` implements the
**standard MIL assumption**: a bag is labeled positive if *any* patch inside it
is positive (`max` of 0/1 labels), and negative only if *every* patch is
negative — this mirrors how a pathologist calls a slide malignant if it
contains even one region of malignant tissue, not based on the majority of the
slide. Each split uses a **different seed** (`SEED`, `SEED+1`, `SEED+2`)
specifically so the train/val/test bag groupings aren't correlated with each
other by sharing the same shuffle. `DataLoader(..., batch_size=1)` is not an
oversight — MIL bags naturally vary in size in a real deployment (this
notebook's synthetic bags happen to be fixed-size, but the model and training
loop are written generally), and batching variable-length sequences would need
padding + masking that this notebook deliberately keeps out of scope; batch
size 1 processes one whole bag per step instead.

## Cell 9 (markdown) — attention-based MIL aggregator

Explains the core idea: a learned attention weight per patch, then a weighted
pool into one bag embedding before classification — and that these same
attention weights are what becomes a saliency overlay later.

## Cell 10 (code) — MIL aggregator model

```python
class AttentionMIL(nn.Module):
    def __init__(self, embed_dim: int, hidden_dim: int = 128):
        super().__init__()
        self.attention = nn.Sequential(
            nn.Linear(embed_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )
        self.classifier = nn.Linear(embed_dim, 1)

    def forward(self, patch_embeddings: torch.Tensor):
        attention_logits = self.attention(patch_embeddings).squeeze(-1)
        attention_weights = F.softmax(attention_logits, dim=0)
        bag_embedding = (attention_weights.unsqueeze(-1) * patch_embeddings).sum(dim=0)
        bag_logit = self.classifier(bag_embedding)
        return bag_logit.squeeze(-1), attention_weights


mil_model = AttentionMIL(embed_dim=EMBED_DIM).to(DEVICE)
print(sum(p.numel() for p in mil_model.parameters()), "parameters")
```

**What/why:** This is the classic Ilse et al. (2018) attention-MIL formulation.
`self.attention` is a tiny 2-layer network that scores each patch embedding
with a single scalar "how much does this patch matter" logit; `Tanh` (rather
than `ReLU`) is the standard choice here because it allows both positive and
negative attention scores before the softmax, which empirically works better
for this specific attention formulation. `F.softmax(..., dim=0)` normalizes
those per-patch scores into weights that sum to 1 **across the patches in one
bag** (dim 0, since there's no batch dimension at batch_size=1) — this is what
turns "raw importance scores" into an actual weighted average.
`(attention_weights.unsqueeze(-1) * patch_embeddings).sum(dim=0)` is the
weighted pooling itself: multiply each patch's embedding by its scalar weight,
then sum across patches to get one bag-level embedding vector — mechanically
identical to a weighted mean, except the weights are *learned* rather than
uniform (1/N per patch), so the model can effectively "zoom in" on the patches
that matter most for the label. The parameter count print is worth noticing:
this model is tiny (a few hundred thousand parameters) compared to the frozen
ViT backbone (~86M) — that asymmetry is the whole point of "light training."

## Cell 11 (markdown) — training loop

Explains that this uses standard binary cross-entropy per bag, and that equal
bag sizes here mean no padding/masking is needed — flagging that a real
variable-bag-size deployment would need that added.

## Cell 12 (code) — train the aggregator

```python
criterion = nn.BCEWithLogitsLoss()
optimizer = torch.optim.Adam(mil_model.parameters(), lr=1e-4, weight_decay=1e-5)


@torch.no_grad()
def evaluate_mil(loader: DataLoader) -> float:
    mil_model.eval()
    all_true, all_score = [], []
    for patch_embeddings, bag_label in loader:
        patch_embeddings = patch_embeddings.squeeze(0).to(DEVICE)
        logit, _ = mil_model(patch_embeddings)
        all_true.append(bag_label.item())
        all_score.append(torch.sigmoid(logit).item())
    return roc_auc_score(all_true, all_score)


NUM_EPOCHS = 15
best_val_auroc = 0.0
best_state_dict = None

for epoch in range(NUM_EPOCHS):
    mil_model.train()
    running_loss = 0.0
    for patch_embeddings, bag_label in train_loader:
        patch_embeddings = patch_embeddings.squeeze(0).to(DEVICE)
        bag_label = bag_label.to(DEVICE)
        optimizer.zero_grad()
        logit, _ = mil_model(patch_embeddings)
        loss = criterion(logit.unsqueeze(0), bag_label)
        loss.backward()
        optimizer.step()
        running_loss += loss.item()

    val_auroc = evaluate_mil(val_loader)
    print(f"epoch {epoch+1:02d}  train_loss={running_loss/len(train_loader):.4f}  val_auroc={val_auroc:.4f}")

    if val_auroc > best_val_auroc:
        best_val_auroc = val_auroc
        best_state_dict = {k: v.cpu().clone() for k, v in mil_model.state_dict().items()}

mil_model.load_state_dict(best_state_dict)
print("Best val AUROC:", best_val_auroc)
```

**What/why:** `patch_embeddings.squeeze(0)` removes the batch dimension of size
1 that `DataLoader` always adds, turning `(1, bag_size, embed_dim)` back into
`(bag_size, embed_dim)`, which is the shape `AttentionMIL.forward` actually
expects. This trains noticeably faster per epoch than the ECG notebook —
because the frozen embeddings are already computed, each training step is just
a forward/backward pass through a tiny linear-attention network, not a full
CNN — which is the concrete payoff of the "adapt, don't retrain" strategy.
Same best-checkpoint-tracking pattern as the ECG notebook: clone to CPU during
the loop, reload at the end, so the final model in memory is the best epoch's,
not necessarily the last one.

## Cell 13 (code) — held-out test evaluation

```python
test_auroc = evaluate_mil(test_loader)
print("Test bag-level AUROC:", test_auroc)
```

**What/why:** One line, but it's the only cell that touches `test_loader` —
same train/val/test discipline as every other notebook in this set, so this
number reflects genuine generalization rather than a metric the model (or the
developer) has already seen and possibly overfit to.

## Cell 14 (markdown) — inspect attention weights

Explains that the per-patch attention weights are the saliency signal that
maps onto `Finding.saliency_ref` and the cross-modal-grounding novelty
candidate from `docs/05-roadmap.md`.

## Cell 15 (code) — inspect one bag's attention

```python
sample_patch_embeddings, sample_bag_label = test_bags[0], test_bag_labels[0].item()
with torch.no_grad():
    logit, attention_weights = mil_model(sample_patch_embeddings.to(DEVICE))
print("Bag label:", sample_bag_label, " predicted prob:", torch.sigmoid(logit).item())
print("Per-patch attention weights:", attention_weights.cpu().numpy().round(3))
```

**What/why:** This cell isn't part of training or evaluation metrics — it
exists to make the model's reasoning **inspectable**. If you're building
toward the cross-modal-grounding differentiator, this is the exact mechanism
you'd extend: instead of just printing the attention weights, you'd map the
highest-weighted patch indices back to their pixel coordinates on the original
slide and render them as an overlay, turning "the model says tumor" into "the
model says tumor, here specifically."

## Cell 16 (code) — save the checkpoint

```python
checkpoint_path = "/kaggle/working/pathology_mil_aggregator.pt"
torch.save(mil_model.state_dict(), checkpoint_path)

metadata = {
    "model": "AttentionMIL",
    "embedding_backbone": EMBED_MODEL_NAME,
    "embed_dim": EMBED_DIM,
    "bag_size": BAG_SIZE,
    "test_bag_auroc": test_auroc,
    "trained_on": "PatchCamelyon (dpdl-benchmark/patch_camelyon), synthetic bags",
    "caveat": "Real deployment must group patches by actual slide ID, not random bags.",
}
with open("/kaggle/working/pathology_mil_aggregator.json", "w") as handle:
    json.dump(metadata, handle, indent=2)

print("Saved:", checkpoint_path)
print(json.dumps(metadata, indent=2))
```

**What/why:** Only the ~tiny `mil_model` state dict is saved here — not the
ViT backbone, which is downloaded fresh from Hugging Face by name
(`EMBED_MODEL_NAME`, recorded in the metadata) whenever this checkpoint is
loaded elsewhere. That's a deliberate storage/reproducibility trade-off: it
keeps the checkpoint file small, at the cost of requiring the exact same
`EMBED_MODEL_NAME` to be available (and unchanged) wherever this is deployed —
which is exactly why the metadata records it explicitly rather than assuming
whoever loads this checkpoint will remember. The `"caveat"` key baked directly
into the metadata JSON (not just this markdown file) is deliberate: it travels
with the checkpoint into any registry entry, so the synthetic-bags limitation
can't get lost in translation.

## Final summary

The distinguishing idea in this notebook, compared to the ECG one: when a
strong pretrained embedding model already exists, training becomes cheap and
fast because you're only fitting a small head on top of frozen, pre-computed
features — the expensive part (representation learning) is already done. The
honest caveat that survives into the saved metadata (synthetic bags, not real
slide groupings) is exactly the kind of thing that must not get lost between a
notebook experiment and a production decision.
