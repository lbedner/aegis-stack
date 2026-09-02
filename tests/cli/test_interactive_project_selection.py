"""Characterization tests for ``interactive_project_selection`` (init flow).

The scheduler and AI paths are pinned by ``test_interactive_scheduler.py``,
``test_scheduler_persistence.py`` and ``test_ai_configuration.py``; this file
pins the remaining branches ahead of the step-engine refactor (issue #487
prep): the worker+redis bundling, auth's database-confirmation dance, the
plain content-service path, and the decline-everything baseline.

Prompt order (must hold for the scripted side_effect lists):
worker, scheduler, database, redis, ingress, observability, htmx, then every
service grouped by ServiceType order: auth, payment, ai, comms, insights,
blog, finance. Accepting worker bundles redis AND skips the redis prompt;
accepting auth without a database inserts a database-confirmation prompt.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from aegis.cli.interactive import interactive_project_selection
from aegis.constants import WorkerBackends


def _prompt_count() -> int:
    """One confirm per screen: every optional component and every service.

    Derived rather than counted, so adding either does not fail this file
    with a bare number about a change made somewhere else.
    """
    from aegis.constants import ComponentNames
    from aegis.core.services import SERVICES

    return len(ComponentNames.INFRASTRUCTURE_ORDER) + len(SERVICES)


class TestProjectSelectionBaseline:
    @patch("typer.confirm")
    def test_decline_everything(self, mock_confirm: Any) -> None:
        mock_confirm.side_effect = [False] * _prompt_count()
        components, scheduler_backend, services, skip_llm = (
            interactive_project_selection()
        )
        assert components == []
        assert scheduler_backend == "memory"
        assert services == []
        assert skip_llm is False
        assert mock_confirm.call_count == _prompt_count()


class TestWorkerRedisBundling:
    @patch("aegis.cli.interactive.select_worker_backend")
    @patch("typer.confirm")
    def test_worker_without_redis_bundles_redis(
        self, mock_confirm: Any, mock_backend: Any
    ) -> None:
        mock_backend.return_value = WorkerBackends.ARQ
        # worker=yes bundles redis and SKIPS the redis prompt; decline the
        # remaining 5 components and 7 services.
        mock_confirm.side_effect = [True] + [False] * 15
        components, _, _, _ = interactive_project_selection()
        assert "redis" in components
        assert "worker" in components
        assert (
            mock_confirm.call_count == _prompt_count() - 1
        )  # redis prompt never shown

    @patch("aegis.cli.interactive.select_worker_backend")
    @patch("typer.confirm")
    def test_redis_still_asked_without_worker(
        self, mock_confirm: Any, mock_backend: Any
    ) -> None:
        mock_backend.return_value = WorkerBackends.ARQ
        # worker=no -> redis gets its own prompt (4th) and can be accepted.
        mock_confirm.side_effect = [False, False, False, True] + [False] * 12
        components, _, _, _ = interactive_project_selection()
        assert components == ["redis"]
        assert mock_confirm.call_count == _prompt_count()

    @patch("aegis.cli.interactive.select_worker_backend")
    @patch("typer.confirm")
    def test_non_default_backend_gets_bracket(
        self, mock_confirm: Any, mock_backend: Any
    ) -> None:
        mock_backend.return_value = WorkerBackends.TASKIQ
        mock_confirm.side_effect = [True] + [False] * 15
        components, _, _, _ = interactive_project_selection()
        assert "worker[taskiq]" in components
        assert "worker" not in components  # bracket form replaces plain name


class TestAuthDatabaseDance:
    @patch("aegis.cli.interactive.interactive_auth_service_config")
    @patch("typer.confirm")
    def test_auth_without_database_confirms_db_addition(
        self, mock_confirm: Any, mock_auth_config: Any
    ) -> None:
        mock_auth_config.return_value = "basic"
        # 8 components declined, auth=yes, db-confirm=yes, then decline
        # payment, ai, comms, insights, blog, finance
        mock_confirm.side_effect = [False] * 8 + [True, True] + [False] * 7
        components, _, services, _ = interactive_project_selection()
        assert "auth[basic]" in services
        assert (
            mock_confirm.call_count == _prompt_count() + 1
        )  # db-confirm prompt was inserted

    @patch("aegis.cli.interactive.interactive_auth_service_config")
    @patch("typer.confirm")
    def test_auth_cancelled_when_db_confirm_declined(
        self, mock_confirm: Any, mock_auth_config: Any
    ) -> None:
        mock_auth_config.return_value = "basic"
        # auth=yes but decline the database confirmation -> auth dropped
        mock_confirm.side_effect = [False] * 8 + [True, False] + [False] * 7
        _, _, services, _ = interactive_project_selection()
        assert services == []

    @patch("aegis.cli.interactive.select_database_engine")
    @patch("aegis.cli.interactive.interactive_auth_service_config")
    @patch("typer.confirm")
    def test_auth_with_database_skips_confirmation(
        self, mock_confirm: Any, mock_auth_config: Any, mock_engine: Any
    ) -> None:
        mock_auth_config.return_value = "rbac"
        # Accepting the database now asks engine; SQLite keeps it plain.
        mock_engine.return_value = "sqlite"
        # database=yes among components (3rd prompt), auth=yes -> no extra
        # db prompt
        mock_confirm.side_effect = (
            [False, False, True, False, False, False, False, False]
            + [True]
            + [False] * 7
        )
        components, _, services, _ = interactive_project_selection()
        assert "database" in components
        assert "auth[rbac]" in services
        assert (
            mock_confirm.call_count == _prompt_count()
        )  # no inserted db-confirm prompt


class TestContentServices:
    @patch("typer.confirm")
    def test_blog_selected_as_plain_name(self, mock_confirm: Any) -> None:
        # Decline everything except blog. Services are asked in ServiceType
        # order, and blog's CONTENT slot is second to last, ahead of
        # finance - so the accept sits one before the end.
        mock_confirm.side_effect = [False] * (_prompt_count() - 2) + [True, False]
        _, _, services, _ = interactive_project_selection()
        assert services == ["blog"]


class ScriptedUI:
    """SelectionUI driven by scripted answers — no monkeypatching needed.

    This is the renderer seam the step engine exists for (issue #487 prep):
    tests (and the future wizard) implement the protocol instead of patching
    typer/questionary internals. Records the transcript for assertions.
    """

    def __init__(
        self,
        confirms: list[bool],
        *,
        worker_backend: str = "arq",
        scheduler_backend: str = "memory",
        database_engine: str = "sqlite",
        postgres_provider: str = "container",
        auth_level: str = "basic",
        ai_config: tuple[str, str, list[str], bool, bool] = (
            "memory",
            "pydantic-ai",
            ["public"],
            False,
            False,
        ),
    ) -> None:
        self._confirms = iter(confirms)
        self._worker_backend = worker_backend
        self._scheduler_backend = scheduler_backend
        self._database_engine = database_engine
        self._postgres_provider = postgres_provider
        self._auth_level = auth_level
        self._ai_config = ai_config
        self.transcript: list[str] = []

    def section(self, title: str, *, newline_before: bool = False) -> None:
        self.transcript.append(f"[section] {title}")

    def confirm(self, prompt: str, *, default: bool = True, context=None) -> bool:
        self.transcript.append(f"[confirm] {prompt}")
        return next(self._confirms)

    def echo(self, message: str = "") -> None:
        self.transcript.append(message)

    def success(self, message: str) -> None:
        self.transcript.append(message)

    def note_auto_added(self, name: str, detail: str = "") -> None:
        self.transcript.append(f"[auto-added {name}{f' {detail}' if detail else ''}]")

    def choose_worker_backend(self) -> str:
        return self._worker_backend

    def choose_scheduler_backend(self) -> str:
        self.transcript.append("[scheduler backend]")
        return self._scheduler_backend

    def choose_database_engine(self, context: str) -> tuple[str, str | None]:
        self.transcript.append(f"[engine for {context}]")
        if self._database_engine == "postgres":
            return self._database_engine, self._postgres_provider
        return self._database_engine, None

    def choose_postgres_provider(self, context: str) -> str:
        self.transcript.append(f"[provider for {context}]")
        return self._postgres_provider

    def configure_auth(self, service_name: str) -> str:
        return self._auth_level

    def configure_ai(
        self, service_name: str, existing_engine: str | None = None
    ) -> tuple[str, str, list[str], bool, bool]:
        return self._ai_config


class TestEngineWithScriptedUI:
    """The engine is testable through the protocol alone."""

    def test_full_stack_selection_no_patching(self) -> None:
        from aegis.cli.interactive import run_project_selection

        # worker=y (bundles redis, redis prompt skipped), scheduler=y
        # (backend via choose_scheduler_backend, db auto-added and skipped),
        # storage=n, ingress=n, observability=n, htmx=n, then services in ServiceType
        # order: auth=y, payment=n, ai=y, comms=n, insights=n,
        # documents=n, blog=y, finance=n
        ui = ScriptedUI(
            confirms=[True, True, False, False, False, False]
            + [True, False, True, False, False, False, True, False],
            worker_backend="taskiq",
            scheduler_backend="postgres",
            database_engine="postgres",
            auth_level="rbac",
            ai_config=("sqlite", "langchain", ["openai"], True, False),
        )
        state = run_project_selection(ui)

        assert state.components == [
            "redis",
            "worker[taskiq]",
            "scheduler[postgres]",
            "database[postgres]",
        ]
        assert state.scheduler_backend == "postgres"
        # One datastore, used everywhere: the renderer's canned "sqlite"
        # backend is overridden by the project engine (postgres), and no
        # second database is appended.
        assert state.services == [
            "auth[rbac]",
            "ai[postgres,langchain,openai,rag]",
            "blog",
        ]
        assert sum("database" in c for c in state.components) == 1

    def test_scheduler_postgres_asks_provider_and_encodes_neon(self) -> None:
        # The scheduler pulls the database in, so IT must ask the
        # container-vs-Neon question the skipped database step would have.
        from aegis.cli.interactive import run_project_selection

        ui = ScriptedUI(
            confirms=[False, True] + [False] * 13,
            scheduler_backend="postgres",
            postgres_provider="neon",
        )
        state = run_project_selection(ui)
        assert "scheduler[postgres]" in state.components
        assert "database[neon]" in state.components
        assert state.postgres_provider == "neon"
        assert "[provider for Scheduler]" in ui.transcript

    def test_ai_postgres_storage_asks_provider_and_encodes_neon(self) -> None:
        # Same rule when AI is what pulls the database in.
        from aegis.cli.interactive import run_project_selection

        ui = ScriptedUI(
            confirms=[False] * 10 + [True] + [False] * 5,
            ai_config=("postgres", "pydantic-ai", ["public"], False, False),
            postgres_provider="neon",
        )
        state = run_project_selection(ui)
        assert state.services == ["ai[postgres,pydantic-ai,public]"]
        assert "database[neon]" in state.components
        assert state.postgres_provider == "neon"
        assert "[provider for AI]" in ui.transcript

    def test_transcript_captures_flow(self) -> None:
        from aegis.cli.interactive import run_project_selection

        ui = ScriptedUI(confirms=[False] * _prompt_count())
        state = run_project_selection(ui)
        assert state.components == []
        assert state.services == []
        confirms = [line for line in ui.transcript if line.startswith("[confirm]")]
        assert len(confirms) == _prompt_count()


class TestDatabaseHostSelection:
    """The standalone database step picks engine and (for postgres) the host.

    Prompt order: worker, scheduler, database, redis, ingress, observability,
    htmx, then the seven services. Accepting only the database (3rd confirm)
    reaches the engine -> host sub-selection.
    """

    def _accept_only_database(self) -> list[bool]:
        # 8 components (database on) + 8 services (all declined).
        return [False, False, True, False, False, False, False, False] + [False] * 8

    def test_standalone_sqlite_stays_plain(self) -> None:
        from aegis.cli.interactive import run_project_selection

        ui = ScriptedUI(confirms=self._accept_only_database(), database_engine="sqlite")
        state = run_project_selection(ui)
        # SQLite is the implicit default: plain ``database``, engine unpinned.
        assert state.components == ["database"]
        assert state.database_engine is None

    def test_standalone_postgres_container(self) -> None:
        from aegis.cli.interactive import run_project_selection

        ui = ScriptedUI(
            confirms=self._accept_only_database(),
            database_engine="postgres",
            postgres_provider="container",
        )
        state = run_project_selection(ui)
        assert state.components == ["database[postgres]"]
        assert state.database_engine == "postgres"
        assert state.postgres_provider == "container"

    def test_standalone_postgres_neon(self) -> None:
        from aegis.cli.interactive import run_project_selection

        ui = ScriptedUI(
            confirms=self._accept_only_database(),
            database_engine="postgres",
            postgres_provider="neon",
        )
        state = run_project_selection(ui)
        # Neon encodes as database[neon]; the engine normalizes to postgres so a
        # later AI/scheduler store that reuses it never inherits "neon".
        assert state.components == ["database[neon]"]
        assert state.database_engine == "postgres"
        assert state.postgres_provider == "neon"
