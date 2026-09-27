"""Every Redis key the worker writes is declared for the keyspace map."""

from fnmatch import fnmatchcase
from importlib.util import find_spec
import uuid

from app.components.worker.events import WORKER_EVENT_STREAM
from app.components.worker.heartbeat import busy_key
from app.components.worker.task_history.shared import (
    _QUEUE_INDEX_PREFIX,
    _TASK_KEY_PREFIX,
)
from app.services.system.redis_keys import families


def _claimed(key: str) -> bool:
    return any(fnmatchcase(key, f.pattern) for f in families())


def _worker_keys() -> list[str]:
    keys = [
        WORKER_EVENT_STREAM,
        busy_key("host:123"),
        f"{_TASK_KEY_PREFIX}{uuid.uuid4().hex}",
        f"{_QUEUE_INDEX_PREFIX}system",
    ]
    job = uuid.uuid4().hex
    if find_spec("taskiq"):  # its queue streams, results and deploy flag
        from app.components.worker.broker import PAUSE_KEY
        from app.components.worker.queues.system import broker

        keys += [
            PAUSE_KEY,
            broker.queue_name,
            f"autoclaim:{broker.consumer_group_name}:{broker.queue_name}",
            job,  # a task result, stored under the bare task id
        ]
    elif find_spec("dramatiq"):  # everything under its namespace
        keys += [
            "dramatiq:heartbeat:system",
            "dramatiq:system",
            "dramatiq:system.msgs",
            "dramatiq:system.DQ",
            "dramatiq:__acks__.worker.system",
            "dramatiq:__heartbeats__",
        ]
    elif find_spec("arq"):
        keys += [
            "arq:queue:system",
            "arq:queue:system:health-check",
            f"arq:job:{job}",
            f"arq:result:{job}",
            f"arq:in-progress:{job}",
            f"arq:retry:{job}",
            "arq:abort",
        ]
    return keys


def test_every_worker_key_is_claimed() -> None:
    unclaimed = [k for k in _worker_keys() if not _claimed(k)]
    assert not unclaimed
