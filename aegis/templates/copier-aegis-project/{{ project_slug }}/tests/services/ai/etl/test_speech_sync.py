"""The speech server's models in the catalog: the local sync registers
what it serves as speech models under its own name, as it does the
inference engine's chat models, so the catalog lists it beside the cloud
voices."""

from collections.abc import Iterator

import pytest
from sqlmodel import Session, select

from app.core import speech_server
from app.services.ai.domains.llm.etl import llm_sync_service
from app.services.ai.domains.llm.etl.llm_sync_service import LLMSyncService
from app.services.ai.domains.llm.etl.results import SyncResult
from app.services.ai.models.llm import LargeLanguageModel, LLMOrg


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """A speech server answering with the models in the list, beside an
    engine serving none (its sync has its own tests)."""
    models: list[str] = []

    async def read(url: str) -> speech_server.SpeechServerReading:
        return speech_server.SpeechServerReading(
            base_url=url, available=True, models=list(models)
        )

    async def nothing(*args: object) -> None:
        """Labs and marks fetch from outside (their own tests)."""

    async def engine_serves_nothing(self: object, dry_run: bool = False) -> SyncResult:
        return SyncResult()

    monkeypatch.setattr(speech_server, "read", read)
    monkeypatch.setattr(speech_server, "reach", lambda s: "http://localhost:8880/v1")
    monkeypatch.setattr(LLMSyncService, "sync_local", engine_serves_nothing)
    monkeypatch.setattr(llm_sync_service, "attach_labs", nothing)
    monkeypatch.setattr(llm_sync_service, "attach_provider_marks", nothing)
    yield models


def _rows(session: Session) -> dict[str, tuple[str, bool, str]]:
    rows = session.exec(
        select(LargeLanguageModel, LLMOrg).join(
            LLMOrg, LLMOrg.id == LargeLanguageModel.served_by_org_id
        )
    ).all()
    return {m.model_id: (m.mode, m.enabled, org.name) for m, org in rows}


async def test_its_own_models_are_speech_models_under_its_name(
    db_session: Session, served: list[str]
) -> None:
    """OpenAI's names it answers to are aliases of its own model, not
    models of its own: the catalog keeps OpenAI's under OpenAI."""
    served += ["kokoro", *sorted(speech_server.OPENAI_MODELS)]

    result = await LLMSyncService(db_session).sync(source="local")

    assert result.models_added == 1
    assert _rows(db_session) == {"kokoro": ("audio_speech", True, speech_server.SLUG)}


async def test_a_model_it_stopped_serving_is_turned_off(
    db_session: Session, served: list[str]
) -> None:
    served.append("kokoro")
    await LLMSyncService(db_session).sync(source="local")
    served[:] = ["kokoro-v2"]

    await LLMSyncService(db_session).sync(source="local")

    assert {m: on for m, (_, on, _) in _rows(db_session).items()} == {
        "kokoro": False,
        "kokoro-v2": True,
    }


async def test_no_server_set_or_answering_adds_nothing_and_is_no_error(
    db_session: Session, served: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server is optional: one not running is not a failed sync."""

    async def down(url: str) -> speech_server.SpeechServerReading:
        return speech_server.SpeechServerReading(base_url=url, available=False)

    monkeypatch.setattr(speech_server, "read", down)
    assert not (await LLMSyncService(db_session).sync(source="local")).errors
    monkeypatch.setattr(speech_server, "reach", lambda s: None)
    assert not (await LLMSyncService(db_session).sync(source="local")).errors
    assert _rows(db_session) == {}


def test_a_tally_merged_in_adds_every_count_and_error() -> None:
    """The speech server's tally joins the engine's whole."""
    total = SyncResult(models_added=1, prices_synced=2, errors=["a"])
    total.merge(SyncResult(models_added=3, prices_synced=4, errors=["b"]))

    assert (total.models_added, total.prices_synced) == (4, 6)
    assert total.errors == ["a", "b"]
