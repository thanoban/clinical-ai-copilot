from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
import uuid


CORRELATION_ID_HEADER = "X-Correlation-Id"

_correlation_id_var: ContextVar[str | None] = ContextVar(
    "aegis_dx_correlation_id",
    default=None,
)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> str | None:
    return _correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> Token[str | None]:
    return _correlation_id_var.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id_var.reset(token)


@contextmanager
def bind_correlation_id(correlation_id: str):
    token = set_correlation_id(correlation_id)
    try:
        yield correlation_id
    finally:
        reset_correlation_id(token)

