from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(slots=True, frozen=True)
class Settings:
    app_name: str
    database_path: Path
    worker_poll_interval_seconds: float


def load_settings() -> Settings:
    database_path = Path(os.getenv("AEGIS_DX_DB_PATH", "var/aegis_dx.db"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        app_name="Aegis-Dx API",
        database_path=database_path,
        worker_poll_interval_seconds=float(
            os.getenv("AEGIS_DX_WORKER_POLL_INTERVAL_SECONDS", "0.05")
        ),
    )

