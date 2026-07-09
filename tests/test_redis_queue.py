from __future__ import annotations

import os
import uuid

import pytest
import redis

from aegis_dx.queueing import RedisStreamCaseQueue


REDIS_URL = os.getenv("AEGIS_DX_TEST_REDIS_URL", "redis://localhost:6379/0")


def _redis_available() -> bool:
    try:
        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2)
        client.ping()
        return True
    except redis.RedisError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(),
    reason="No reachable Redis at AEGIS_DX_TEST_REDIS_URL (start it with `docker compose up -d redis`).",
)


@pytest.fixture
def queue() -> RedisStreamCaseQueue:
    return RedisStreamCaseQueue(REDIS_URL, consumer_name=f"test-consumer-{uuid.uuid4()}")


def test_enqueue_dequeue_round_trips(queue: RedisStreamCaseQueue) -> None:
    case_id = str(uuid.uuid4())
    queue.enqueue(case_id)

    dequeued = queue.dequeue(timeout=2.0)

    assert dequeued == case_id


def test_dequeue_returns_none_when_empty(queue: RedisStreamCaseQueue) -> None:
    result = queue.dequeue(timeout=0.2)

    assert result is None


def test_ack_after_dequeue_does_not_error(queue: RedisStreamCaseQueue) -> None:
    case_id = str(uuid.uuid4())
    queue.enqueue(case_id)
    dequeued = queue.dequeue(timeout=2.0)

    queue.ack(dequeued)


def test_fifo_order_is_preserved_for_a_single_consumer(queue: RedisStreamCaseQueue) -> None:
    case_ids = [str(uuid.uuid4()) for _ in range(3)]
    for case_id in case_ids:
        queue.enqueue(case_id)

    dequeued = []
    for _ in case_ids:
        item = queue.dequeue(timeout=2.0)
        assert item is not None
        dequeued.append(item)
        queue.ack(item)

    assert dequeued == case_ids
