from __future__ import annotations

from queue import Empty, Queue
from typing import Any, Protocol


class CaseQueuePort(Protocol):
    """Durable-queue abstraction the workflow runtime dispatches case work through.

    Swappable so a single in-process queue.Queue can back tests/dev, while a
    Redis Streams consumer group backs a real deployment where the worker runs
    as a separate process from the API (docs/08's target architecture).
    """

    def enqueue(self, case_id: str) -> None: ...

    def dequeue(self, timeout: float) -> str | None:
        """Block up to `timeout` seconds for the next case id, or return None."""

    def ack(self, case_id: str) -> None:
        """Acknowledge successful processing so the item isn't redelivered."""


class InProcessCaseQueue:
    """Default queue backend: an in-memory queue.Queue in the same process.

    Matches the current walking-skeleton reality documented in docs/08 - no
    cross-process durability, but zero external dependencies for tests/dev.
    """

    def __init__(self) -> None:
        self._queue: Queue[str] = Queue()

    def enqueue(self, case_id: str) -> None:
        self._queue.put(case_id)

    def dequeue(self, timeout: float) -> str | None:
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def ack(self, case_id: str) -> None:
        # Nothing to acknowledge - an in-process queue has no redelivery concept.
        return None


class RedisStreamCaseQueue:
    """Durable queue backed by a Redis Stream + consumer group.

    Provides at-least-once delivery across process restarts: a case id isn't
    considered done until `ack()` (XACK) is called, so a worker crash mid-case
    leaves it claimable by another consumer instead of losing it - the property
    docs/08 calls out as missing from the in-process queue.
    """

    _STREAM_KEY = "aegis_dx:case_queue"
    _GROUP_NAME = "aegis_dx_workers"

    def __init__(self, redis_url: str, *, consumer_name: str = "worker-1") -> None:
        import redis

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._consumer_name = consumer_name
        self._ensure_group()

    def _ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(name=self._STREAM_KEY, groupname=self._GROUP_NAME, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001 - redis raises a plain ResponseError we must string-match
            if "BUSYGROUP" not in str(exc):
                raise

    def enqueue(self, case_id: str) -> None:
        self._redis.xadd(self._STREAM_KEY, {"case_id": case_id})

    def dequeue(self, timeout: float) -> str | None:
        block_ms = max(1, int(timeout * 1000))
        # redis-py's stubs type xreadgroup()'s response generically across its
        # many overload shapes; at runtime with decode_responses=True this is
        # exactly [(stream_key, [(message_id, {field: value})])], so we take
        # the return as Any and unpack it ourselves rather than fight the stub.
        response: Any = self._redis.xreadgroup(
            groupname=self._GROUP_NAME,
            consumername=self._consumer_name,
            streams={self._STREAM_KEY: ">"},
            count=1,
            block=block_ms,
        )
        if not response:
            return None
        _stream_key, messages = response[0]
        message_id, fields = messages[0]
        self._pending_message_id = message_id
        return fields.get("case_id")

    def ack(self, case_id: str) -> None:
        message_id = getattr(self, "_pending_message_id", None)
        if message_id is not None:
            self._redis.xack(self._STREAM_KEY, self._GROUP_NAME, message_id)
            self._pending_message_id = None
