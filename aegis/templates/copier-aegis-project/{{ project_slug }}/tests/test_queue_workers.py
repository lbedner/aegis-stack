"""Per-queue worker settings: validated on load, one default for the rest."""

from pydantic import ValidationError
import pytest

from app.core.queue_workers import QueueWorker, queue_worker


class TestQueueWorker:
    def test_a_misspelled_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            QueueWorker.model_validate({"concurency": 5})

    def test_concurrency_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            QueueWorker(concurrency=0)


class TestLookup:
    def test_a_listed_queue_gets_its_own_settings(self) -> None:
        queues = {"load_test": QueueWorker(concurrency=50)}
        assert queue_worker("load_test", queues, QueueWorker()).concurrency == 50

    def test_any_other_queue_gets_the_default(self) -> None:
        default = QueueWorker(concurrency=7)
        assert queue_worker("media", {}, default).concurrency == 7


def test_settings_carry_the_queues_and_read_them_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("WORKER_QUEUES", '{"load_test": {"concurrency": 100}}')
    settings = Settings()
    assert settings.WORKER_QUEUES["load_test"].concurrency == 100
    assert settings.WORKER_QUEUE_DEFAULT.concurrency > 0


def test_a_bad_value_in_the_environment_stops_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("WORKER_QUEUES", '{"system": {"concurrency": -1}}')
    with pytest.raises(ValidationError):
        Settings()


def test_concurrency_for_reads_the_live_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import queue_workers
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "WORKER_QUEUES", {"system": QueueWorker(concurrency=4)}
    )
    monkeypatch.setattr(settings, "WORKER_QUEUE_DEFAULT", QueueWorker(concurrency=9))
    assert queue_workers.concurrency_for("system") == 4
    assert queue_workers.concurrency_for("media") == 9


def test_queue_metadata_carries_the_configured_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the health check and the dashboards read, not a constant."""
    from app.components.worker import queue_discovery
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "WORKER_QUEUES", {"system": QueueWorker(concurrency=4)}
    )
    assert queue_discovery.build_metadata("system", [])["max_jobs"] == 4
    assert queue_discovery.build_metadata("system", [], max_jobs=7)["max_jobs"] == 7


def test_each_queue_has_a_backlog_limit() -> None:
    """How long the oldest job may wait before the queue counts as backed up."""
    assert QueueWorker().max_wait_seconds > 0
    with pytest.raises(ValidationError):
        QueueWorker(max_wait_seconds=0)
