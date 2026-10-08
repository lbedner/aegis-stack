"""Service attribution works through the real logging and collection pipeline."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from io import StringIO
import logging
import sys
from typing import Any

import pytest
import structlog
from structlog.contextvars import bound_contextvars, get_contextvars

from app.core import log
from app.core.config import settings
from app.core.log_records import LogAssembler
from app.core.runtime import parse_log_line
from app.services.system.errors.normalize import normalize


@pytest.fixture(autouse=True)
def registered_services(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.system import health

    monkeypatch.setattr(
        health,
        "registered_health_names",
        lambda: {
            "components": (),
            "services": ("future_service", "new_service"),
        },
    )


@pytest.fixture(params=["dev", "prod"])
def output(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[StringIO]:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_config = structlog.get_config()
    stream = StringIO()
    monkeypatch.setattr(log, "_logging_configured", False)
    monkeypatch.setattr(settings, "APP_ENV", request.param)
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    log.setup_logging(stream)
    try:
        yield stream
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.configure(**saved_config)


def function_at(path: str, body: str) -> Callable[[], Any]:
    namespace: dict[str, Any] = {"logger": log.logger}
    exec(compile("def run():\n" + body, path, "exec"), namespace)
    return namespace["run"]


def retained(output: StringIO) -> Any:
    assembler = LogAssembler()
    records = []
    for line in output.getvalue().splitlines():
        records.extend(
            assembler.feed("container", parse_log_line(line, "stdout"), now=0)
        )
    records.extend(assembler.flush())
    occurrences = [
        normalize(
            record,
            page="server",
            service="webserver",
            container_name="web-1",
            ordinal=index,
            observed_at=datetime.now(UTC),
        )
        for index, record in enumerate(records)
    ]
    return next(occurrence for occurrence in occurrences if occurrence is not None)


@pytest.mark.parametrize("service", ["ai", "auth", "future_service"])
def test_registered_service_folders_are_attributed(
    output: StringIO, service: str
) -> None:
    function_at(
        f"/code/app/services/{service}/nested/operations.py",
        '    logger.error("operation failed")\n',
    )()
    occurrence = retained(output)
    assert occurrence.app_service == service
    assert occurrence.service == "webserver"
    assert occurrence.fields["emitting_service"] == service


def test_outer_handler_retains_exception_origin(output: StringIO) -> None:
    fails = function_at(
        "/code/app/services/ai/service/chat.py",
        '    raise RuntimeError("provider failed")\n',
    )
    try:
        fails()
    except RuntimeError:
        log.logger.exception("HTTP request failed")
    assert retained(output).app_service == "ai"


def test_chained_exception_keeps_original_service(output: StringIO) -> None:
    fails = function_at(
        "/code/app/services/ai/provider.py",
        '    raise RuntimeError("provider failed")\n',
    )
    wrapper = function_at(
        "/code/app/services/comms/delivery.py",
        '    try:\n        fails()\n    except RuntimeError as error:\n        raise ValueError("delivery failed") from error\n',
    )
    wrapper.__globals__["fails"] = fails
    try:
        wrapper()
    except ValueError:
        log.logger.exception("Request failed")
    assert retained(output).app_service == "ai"


def test_shared_helper_inherits_scoped_job_owner(output: StringIO) -> None:
    before = get_contextvars()
    helper = function_at(
        "/code/app/core/shared.py", '    logger.error("shared operation failed")\n'
    )
    with bound_contextvars(app_service="ai"):
        helper()
    assert retained(output).app_service == "ai"
    assert get_contextvars() == before


def test_unrelated_runtime_error_remains_unattributed(output: StringIO) -> None:
    log.logger.error("runtime failed")
    assert retained(output).app_service is None


def test_standard_library_logging_is_also_attributed(output: StringIO) -> None:
    record = logging.LogRecord(
        "library",
        logging.ERROR,
        "/code/app/services/ai/jobs.py",
        1,
        "job failed",
        (),
        None,
    )
    logging.getLogger().handle(record)
    assert retained(output).app_service == "ai"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/code/app/services/ai/chat.py", "ai"),
        ("app/services/new_service/operations.py", "new_service"),
        (r"C:\project\app\services\auth\session.py", "auth"),
        ("/code/app/components/backend/api/ai/chat.py", None),
        ("/code/vendor/services/ai/chat.py", None),
        ("/code/app/services.py", None),
        ("/code/app/services/../core.py", None),
        ("/code/app/services/ai", None),
    ],
)
def test_service_path_convention(path: str, expected: str | None) -> None:
    from app.core.log_attribution import service_from_path

    assert service_from_path(path) == expected


def test_exception_tuple_and_suppressed_context() -> None:
    from app.core.log_attribution import add_service_attribution

    fails = function_at(
        "/code/app/services/ai/jobs.py", '    raise RuntimeError("failed")\n'
    )
    try:
        fails()
    except RuntimeError:
        result = add_service_attribution(None, "error", {"exc_info": sys.exc_info()})
        assert result["app_service"] == "ai"
        try:
            raise ValueError("unrelated") from None
        except ValueError:
            result = add_service_attribution(None, "error", {"exc_info": True})
            assert "app_service" not in result


async def test_job_execution_sets_owner_and_restores_context() -> None:
    import asyncio

    from app.core.schedule import ServiceJob

    seen: list[str | None] = []

    async def shared_job() -> None:
        await asyncio.sleep(0)
        seen.append(get_contextvars().get("app_service"))

    jobs = [
        ServiceJob(shared_job, name, name, {}, app_service=name)
        for name in ("ai", "auth")
    ]
    before = get_contextvars()
    await asyncio.gather(*(job.run() for job in jobs))
    assert sorted(seen) == ["ai", "auth"]
    assert get_contextvars() == before


async def test_escaped_job_error_keeps_owner_after_context_cleanup() -> None:
    from app.core.log_attribution import add_service_attribution
    from app.core.schedule import ServiceJob

    async def shared_job() -> None:
        raise RuntimeError("shared helper failed")

    job = ServiceJob(shared_job, "job", "Job", {}, app_service="ai")
    before = get_contextvars()
    with pytest.raises(RuntimeError) as caught:
        await job.run()
    assert get_contextvars() == before
    result = add_service_attribution(None, "error", {"exc_info": caught.value})
    assert result["app_service"] == "ai"


def test_empty_execution_owner_remains_unattributed(output: StringIO) -> None:
    with bound_contextvars(app_service=None):
        log.logger.error("unowned task failed")
    assert retained(output).app_service is None


async def test_streaming_exception_is_attributed_when_logged_after_iteration(
    output: StringIO,
) -> None:
    namespace: dict[str, Any] = {}
    exec(
        compile(
            'async def stream():\n    yield "chunk"\n    raise RuntimeError("stream failed")\n',
            "/code/app/services/ai/service/streaming.py",
            "exec",
        ),
        namespace,
    )
    chunks = []
    try:
        async for chunk in namespace["stream"]():
            chunks.append(chunk)
    except RuntimeError:
        log.logger.exception("HTTP stream failed")
    assert chunks == ["chunk"]
    assert retained(output).app_service == "ai"


async def test_scheduler_entry_point_uses_discovered_job_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import schedule

    seen = []

    async def shared_job() -> str:
        seen.append(get_contextvars().get("app_service"))
        return "done"

    job = schedule.ServiceJob(shared_job, "sync", "Sync", {}, app_service="ai")
    monkeypatch.setattr(schedule, "service_jobs", lambda: (job,))
    assert await schedule.run_service_job("sync") == "done"
    assert seen == ["ai"]
    with pytest.raises(ValueError, match="Unknown service job"):
        await schedule.run_service_job("missing")


async def test_preserved_job_origin_survives_an_outer_service_frame() -> None:
    from app.core.log_attribution import exception_origin
    from app.core.schedule import ServiceJob

    async def shared_job() -> None:
        raise RuntimeError("shared operation failed")

    job = ServiceJob(shared_job, "sync", "Sync", {}, app_service="ai")
    namespace: dict[str, Any] = {"job": job}
    exec(
        compile(
            "async def caller():\n    await job.run()\n",
            "/code/app/services/comms/dispatch.py",
            "exec",
        ),
        namespace,
    )
    with pytest.raises(RuntimeError) as caught:
        await namespace["caller"]()
    assert exception_origin(caught.value) == "ai"


@pytest.mark.parametrize("folder", ["system", "change_queue", "random_helper"])
def test_shared_and_unregistered_folders_are_not_application_services(
    output: StringIO,
    folder: str,
) -> None:
    function_at(
        f"/code/app/services/{folder}/helper.py", '    logger.error("helper failed")\n'
    )()
    event = retained(output)
    assert event.app_service is None
    assert "emitting_service" not in event.fields


def test_unregistered_context_cannot_assign_an_application_service(
    output: StringIO,
) -> None:
    with bound_contextvars(app_service="system"):
        log.logger.error("shared helper failed")
    assert retained(output).app_service is None
