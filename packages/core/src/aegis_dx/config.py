from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(slots=True, frozen=True)
class Settings:
    app_name: str
    database_path: Path
    database_url: str | None
    redis_url: str | None
    worker_poll_interval_seconds: float
    cxr_specialist_backend: str
    cxr_specialist_endpoint_url: str | None
    cxr_specialist_api_key: str | None
    cxr_specialist_model_version: str
    cxr_specialist_timeout_seconds: float
    verifier_endpoint_url: str | None
    verifier_api_key: str | None
    verifier_model_version: str
    verifier_timeout_seconds: float


def load_settings() -> Settings:
    database_path = Path(os.getenv("AEGIS_DX_DB_PATH", "var/aegis_dx.db"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        app_name="Aegis-Dx API",
        database_path=database_path,
        database_url=os.getenv("AEGIS_DX_DATABASE_URL"),
        redis_url=os.getenv("AEGIS_DX_REDIS_URL"),
        worker_poll_interval_seconds=float(
            os.getenv("AEGIS_DX_WORKER_POLL_INTERVAL_SECONDS", "0.05")
        ),
        cxr_specialist_backend=os.getenv("AEGIS_DX_CXR_SPECIALIST_BACKEND", "http"),
        cxr_specialist_endpoint_url=os.getenv("AEGIS_DX_CXR_SPECIALIST_ENDPOINT_URL"),
        cxr_specialist_api_key=os.getenv("AEGIS_DX_CXR_SPECIALIST_API_KEY"),
        cxr_specialist_model_version=os.getenv(
            "AEGIS_DX_CXR_SPECIALIST_MODEL_VERSION", "medgemma-cxr-v1"
        ),
        cxr_specialist_timeout_seconds=float(
            os.getenv("AEGIS_DX_CXR_SPECIALIST_TIMEOUT_SECONDS", "8.0")
        ),
        verifier_endpoint_url=os.getenv("AEGIS_DX_VERIFIER_ENDPOINT_URL"),
        verifier_api_key=os.getenv("AEGIS_DX_VERIFIER_API_KEY"),
        verifier_model_version=os.getenv("AEGIS_DX_VERIFIER_MODEL_VERSION", "verifier-critic-v1"),
        verifier_timeout_seconds=float(os.getenv("AEGIS_DX_VERIFIER_TIMEOUT_SECONDS", "8.0")),
    )

