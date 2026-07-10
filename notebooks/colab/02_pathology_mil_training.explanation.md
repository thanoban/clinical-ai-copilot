# 02_pathology_mil_training.ipynb (Colab) — explained cell by cell

Companion to [02_pathology_mil_training.ipynb](02_pathology_mil_training.ipynb).
Colab port of
[../kaggle/02_pathology_mil_training.ipynb](../kaggle/02_pathology_mil_training.ipynb)
— and the **simplest port in this whole set**, because the Kaggle version
already loads its dataset via the Hugging Face `datasets` library rather than
a Kaggle-specific mount. Full reasoning for the shared cells (model, training
loop, attention weights, why patches instead of full slides) lives in
[../kaggle/02_pathology_mil_training.explanation.md](../kaggle/02_pathology_mil_training.explanation.md) —
this file covers only what's actually different here.

## Why this port needed almost no changes

The other three Colab notebooks in this set exist because their Kaggle
versions depend on `/kaggle/input` datasets or Kaggle-specific mirrors. This
one doesn't — `load_dataset("dpdl-benchmark/patch_camelyon", ...)` pulls
directly from the Hugging Face Hub over the internet, which works identically
on Kaggle and Colab. The only things that change are: mounting Drive, and
caching the (slow to compute) embeddings there so a disconnect doesn't cost you
the most expensive step in the notebook.

---

## Cell 1 (markdown) — overview

States plainly that this is the easiest port — same HF `datasets` loading as
Kaggle — and that the two real additions are the GPU check and Drive-based
checkpoint/embedding storage.

## Cell 2 (code) — install dependencies

```python
!pip install -q datasets transformers accelerate
```

Identical to the Kaggle notebook's cell 2.

## Cell 3 (code) — mount Drive

```python
from google.colab import drive
drive.mount("/content/drive")

import os
DRIVE_WORKDIR = "/content/drive/MyDrive/aegis-dx/pathology-mil"
os.makedirs(DRIVE_WORKDIR, exist_ok=True)
print("Persistent working dir:", DRIVE_WORKDIR)
```

**What/why:** Same Drive-mount pattern as every Colab notebook in this set —
see
[../colab/01_ecg_ptbxl_training.explanation.md](01_ecg_ptbxl_training.explanation.md)'s
cell 3 for the mechanics. The reason it matters *particularly* here: the next
few cells' embedding-extraction step is the slowest part of this notebook (a
full ViT forward pass for tens of thousands of patches), and losing that work
to a disconnect would be the most annoying possible failure mode.

## Cells 4–5 — imports, load PatchCamelyon

Identical to the Kaggle notebook's cells 3–4 — same seeding, same frozen ViT
loading, same `TRAIN_PATCH_LIMIT`/`VAL_PATCH_LIMIT`/`TEST_PATCH_LIMIT` scoping
for a manageable single-GPU run.

## Cell 6 (code) — embed once, cache to Drive

```python
@torch.no_grad()
def embed_split(raw_split, batch_size: int = 64) -> tuple[torch.Tensor, torch.Tensor]:
    ...  # identical extraction logic to Kaggle's cell 6


def embed_or_load_cached(raw_split, cache_name: str):
    cache_path = os.path.join(DRIVE_WORKDIR, cache_name)
    if os.path.exists(cache_path):
        cached = torch.load(cache_path)
        return cached["embeddings"], cached["labels"]
    embeddings, labels = embed_split(raw_split)
    torch.save({"embeddings": embeddings, "labels": labels}, cache_path)
    return embeddings, labels


train_embeddings, train_labels = embed_or_load_cached(raw_train, "train_embeddings.pt")
val_embeddings, val_labels = embed_or_load_cached(raw_val, "val_embeddings.pt")
test_embeddings, test_labels = embed_or_load_cached(raw_test, "test_embeddings.pt")
print(train_embeddings.shape, val_embeddings.shape, test_embeddings.shape)
```

**What/why — this wrapper is the one real addition over the Kaggle version.**
The Kaggle notebook calls `embed_split` directly, once, because a Kaggle
session that's still running has that data in memory for as long as you need
it. On Colab, `embed_or_load_cached` adds a caching layer around the same
`embed_split` function: it checks Drive first, and only pays the expensive
embedding-extraction cost if no cached tensor exists yet. `torch.save({...})`
bundles both the embeddings and their labels into one dict-shaped file so a
single `torch.load` restores both together, rather than needing two separate
cache files that could get out of sync with each other. Practically, this
means: run this notebook once, disconnect, come back tomorrow and run it
again — the embedding step becomes near-instant the second time, loading from
Drive instead of re-running the ViT over every patch.

## Cells 7–8 — build bags, MIL model

Identical to the Kaggle notebook's cells 8 and 10 — same synthetic-bag
grouping (with the same caveat that a real deployment must group by actual
slide ID), same `AttentionMIL` architecture.

## Cell 9 (code) — train, checkpointing to Drive

```python
criterion = nn.BCEWithLogitsLoss()
optimizer = torch.optim.Adam(mil_model.parameters(), lr=1e-4, weight_decay=1e-5)
CHECKPOINT_PATH = os.path.join(DRIVE_WORKDIR, "pathology_mil_aggregator_best.pt")

...  # evaluate_mil identical to Kaggle

NUM_EPOCHS = 15
best_val_auroc = 0.0

for epoch in range(NUM_EPOCHS):
    ...
    if val_auroc > best_val_auroc:
        best_val_auroc = val_auroc
        torch.save(mil_model.state_dict(), CHECKPOINT_PATH)

mil_model.load_state_dict(torch.load(CHECKPOINT_PATH))
```

**What/why:** Same "write straight to Drive on every improvement" pattern as
the ECG Colab notebook, instead of the Kaggle version's in-memory
best-state-dict tracking — see
[01_ecg_ptbxl_training.explanation.md](01_ecg_ptbxl_training.explanation.md)'s
cell 10 for the full reasoning. Given this training loop only takes about an
hour (the aggregator is tiny), the disconnect risk is lower here than for the
BraTS notebook, but the pattern costs nothing to apply consistently.

## Cell 10 (code) — held-out test evaluation + metadata

```python
test_auroc = evaluate_mil(test_loader)
print("Test bag-level AUROC:", test_auroc)

metadata = {
    "model": "AttentionMIL",
    "embedding_backbone": EMBED_MODEL_NAME,
    "embed_dim": EMBED_DIM,
    "bag_size": BAG_SIZE,
    "test_bag_auroc": test_auroc,
    "trained_on": "PatchCamelyon (dpdl-benchmark/patch_camelyon), synthetic bags",
    "trained_on_platform": "Google Colab",
    "caveat": "Real deployment must group patches by actual slide ID, not random bags.",
}
with open(os.path.join(DRIVE_WORKDIR, "pathology_mil_aggregator_best.json"), "w") as handle:
    json.dump(metadata, handle, indent=2)
print(json.dumps(metadata, indent=2))
```

**What/why:** Same test-evaluation discipline and metadata-sidecar pattern as
Kaggle, with `"trained_on_platform": "Google Colab"` added for the same
registry-provenance reason described in the ECG notebook's explanation. The
`"caveat"` about synthetic bags is preserved verbatim — it's a fact about the
*data*, not the platform, so it travels unchanged into this version's metadata
too.

## Cell 11 (markdown) — next steps

Points back to the Kaggle notebook's final cell — swap synthetic bags for
real slide-grouped bags before trusting this AUROC, confirm the embedding
backbone choice, then subgroup breakdown + calibration + registry entry.

## Final summary

This port demonstrates the other end of the spectrum from the BraTS/Echo
notebooks: when a notebook already sources its data platform-independently
(via Hugging Face rather than a Kaggle-specific mount), porting to Colab is
almost entirely about **persistence** — mounting Drive and caching the
expensive intermediate result (embeddings) there — rather than about data
acquisition at all.
