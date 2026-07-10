"""Real, locally-runnable model wrappers for the pretrained checkpoints in
docs/04-data-models.md - as opposed to the HTTP-based adapters in
specialists.py/trust.py, which call an externally-hosted endpoint.

Each wrapper lazy-loads its model on first use (not at import time) so
importing this package never triggers a download, and stays fast when the
optional ML dependency isn't installed.
"""
