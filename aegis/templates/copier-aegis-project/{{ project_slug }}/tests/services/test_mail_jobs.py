"""Where a mail import runs: on the worker where the stack has one
(``start_job``), else as a task here. The bytes travel through storage;
the queue carries the key."""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage
from app.services.mail import jobs
from app.services.system import job_store
from tests._mbox import mbox_bytes, message
from tests._session import opens

pytestmark = pytest.mark.usefixtures("no_mail_hooks")

WORKER = importlib.util.find_spec("app.components.worker") is not None


class TestTheImportIsAJob:
    async def test_the_job_reads_the_file_from_storage(
        self,
        async_db_session: AsyncSession,
        files: FilesystemStorage,
        dispatched: list[int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(jobs, "get_async_session", opens(async_db_session))
        key = await files.put(mbox_bytes([message(body="one"), message(body="two")]))
        said: list[str] = []

        done = await jobs.run_mail_import(
            key, file_name="export.mbox", owner_user_id=None, report=said.append
        )

        assert (done["messages_new"], done["letters_filed"]) == (2, 2)
        assert said

    @pytest.mark.skipif(not WORKER, reason="no worker in this stack")
    async def test_it_is_queued_as_its_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        queued: list[tuple[Any, ...]] = []

        async def queue_job(*args: Any) -> str:
            queued.append(args)
            return "job-1"

        monkeypatch.setattr(job_store, "queue_job", queue_job)

        job_id = await jobs.start_mail_import(
            "sha256/abc", file_name="export.mbox", owner_user_id=None
        )

        assert job_id == "job-1"
        assert queued == [
            (
                "mail-import:export.mbox",
                "mail_import_task",
                "sha256/abc",
                "export.mbox",
                None,
            )
        ]

    @pytest.mark.skipif(not WORKER, reason="no worker in this stack")
    async def test_the_worker_narrates_into_the_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        labels: list[str] = []

        async def narrate(job_id: str, work: Any) -> dict[str, Any]:
            return await work(labels.append)

        async def run(
            storage_key: str, *, file_name: str, owner_user_id: int | None, report: Any
        ) -> dict[str, int]:
            report("Read 1 of 1")
            return {"messages_new": 1}

        monkeypatch.setattr(jobs, "narrate", narrate)
        monkeypatch.setattr(jobs, "run_mail_import", run)

        result = await jobs.run_mail_import_job("job", "sha256/abc", "x.mbox", None)

        assert result == {"messages_new": 1} and labels == ["Read 1 of 1"]
