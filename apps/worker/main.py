"""Standalone worker entrypoint.

Runs the same WorkflowRuntime processing loop as the API process, but on its
own - the point of the Redis-Streams-backed CaseQueuePort is that intake
(the API) and processing (this worker) no longer have to share a process or a
machine. Requires AEGIS_DX_REDIS_URL and (for a real deployment)
AEGIS_DX_DATABASE_URL to be set; falls back to the in-process queue/SQLite
only for local smoke-testing, in which case running this as a second process
alongside the API won't share state.

Usage:
    python -m apps.worker.main
"""

from __future__ import annotations

import logging
import signal
import time

from aegis_dx.api.app import _build_runtime
from aegis_dx.config import load_settings

logger = logging.getLogger("aegis_dx.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    backend = "redis" if settings.redis_url else "in-process"
    store_backend = "postgres" if settings.database_url else "sqlite"
    logger.info("Starting Aegis-Dx worker (queue=%s, store=%s)", backend, store_backend)

    runtime = _build_runtime(settings)
    runtime.start()

    stop = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not stop:
            time.sleep(0.5)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
