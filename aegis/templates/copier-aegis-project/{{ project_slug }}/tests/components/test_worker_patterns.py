"""The worker task pattern, detected from the queues' registries.

The same on every engine: ``registry.queue_tasks`` finds the tasks and
each engine's wrapper is unwrapped to the function it runs.
"""

from typing import Any

from pydantic import BaseModel

from app.components.worker import registry
from app.components.worker.patterns import TASK, Task
from app.services.system import patterns


def _findings(func: Any) -> list[str]:
    task = Task("q", func.__name__, func)
    return [r.key for r in TASK.rules if not r.exempt(task) and not r.check(task)]


def test_every_registered_task_is_an_instance() -> None:
    registered = {
        f"{queue}.{name}"
        for queue in registry.discover_worker_queues()
        for name in registry.queue_tasks(queue)
    }
    assert {i.label for i in patterns.report(TASK).instances} == registered


def test_every_rule_says_why() -> None:
    assert all(rule.why for rule in TASK.rules)


def test_a_task_handing_work_to_a_lazily_imported_service_follows() -> None:
    async def delegate(job_id: str, attempts: int) -> dict[str, bool]:
        """Delegates to a service imported where it is used."""
        from app.services.system.health import get_system_status

        return {"ok": bool(await get_system_status())}

    assert _findings(delegate) == []


def test_a_call_through_an_attribute_reaches_the_service() -> None:
    from app.services.system.health import get_system_status

    class Job:
        func = staticmethod(get_system_status)

    job = Job()

    async def run() -> dict[str, bool]:
        """A scheduled job's wrapper."""
        return {"ok": bool(await job.func())}

    assert patterns.calls_service(run)


def test_arguments_that_are_not_json_are_flagged() -> None:
    class Account(BaseModel):
        id: int

    async def charge(account: Account) -> dict[str, int]:
        """Takes a model across the broker."""
        return {"id": account.id}

    assert "json-args" in _findings(charge)


def test_str_enums_and_keyword_extras_cross_as_json() -> None:
    from enum import StrEnum

    class Kind(StrEnum):
        CPU = "cpu"

    async def run(ctx: dict[str, Any], kind: Kind, **kwargs: Any) -> dict[str, str]:
        """arq's shape: a context dict, an enum, and keyword extras."""
        return {"kind": kind}

    assert "json-args" not in _findings(run)


def test_a_json_object_result_passes_and_a_bare_any_does_not() -> None:
    async def typed() -> dict[str, Any]:
        """Returns a JSON object."""
        return {}

    async def untyped() -> Any:
        """Returns anything."""
        return None

    assert "json-result" not in _findings(typed)
    assert "json-result" in _findings(untyped)


def test_a_log_line_is_not_work() -> None:
    import logging

    logger = logging.getLogger(__name__)

    async def ping() -> dict[str, str]:
        """Answers, and logs that it did."""
        logger.debug("ping")
        return {"status": "ok"}

    assert "thin" not in _findings(ping)


def test_the_canonical_example_follows_every_rule_and_step() -> None:
    report = patterns.report(TASK)
    if not report.instances:
        return
    assert report.canonical is not None
    assert report.canonical.findings == []
