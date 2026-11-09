"""Adding an option to an installed service leaves the project as init would.

``add-service "ai[...,voice]"`` on a project with ``ai`` set ``ai_voice`` and
copied the voice-only files, but every file it already had kept its first
render, voice off: ``speech.py`` stayed a stub, the router never mounted it,
and ``AIService`` had no ``stt``/``tts``. It also re-created files the
project had deleted, because it copied the service's whole footprint again.
"""

from __future__ import annotations

from pathlib import Path

from aegis.core.manual_updater import ManualUpdater

from .conftest import ProjectFactory

AI = "app/services/ai"
SPEECH = "app/components/backend/api/ai/speech.py"
EVALS_PAGE = "app/components/web_frontend/overseer_ai_evals.py"


def _add_voice(project: Path) -> None:
    result = ManualUpdater(project).add_component(
        "ai", {"ai_voice": True}, run_post_gen=False
    )
    assert result.success, result.error_message


def test_existing_files_take_the_new_option(project_factory: ProjectFactory) -> None:
    project = project_factory("base_with_ai_sqlite_service")
    assert "def stt" not in (project / f"{AI}/service/base.py").read_text()

    _add_voice(project)

    assert "def stt" in (project / f"{AI}/service/base.py").read_text()
    assert "speech" in (project / "app/components/backend/api/ai/router.py").read_text()
    assert "/transcribe" in (project / SPEECH).read_text()
    assert (project / f"{AI}/domains/voice/__init__.py").exists()
    # The voice tables' package arrives with the option.
    assert (project / f"{AI}/models/voice/profile.py").exists()


def test_an_edited_file_keeps_its_edit(project_factory: ProjectFactory) -> None:
    project = project_factory("base_with_ai_sqlite_service")
    base = project / f"{AI}/service/base.py"
    base.write_text(base.read_text() + "\n\n# kept by the project\n")

    _add_voice(project)

    text = base.read_text()
    assert "# kept by the project" in text
    assert "def stt" in text


def test_a_file_the_project_deleted_stays_deleted(
    project_factory: ProjectFactory,
) -> None:
    project = project_factory("base_with_ai_sqlite_service")
    deleted = project / "app/components/backend/api/ai/analytics.py"
    deleted.unlink()

    _add_voice(project)

    assert not deleted.exists()


def test_an_auth_level_upgrade_takes_too(project_factory: ProjectFactory) -> None:
    """Auth's level used a hand-kept list of files to overwrite, edits and
    all; it is the same option upgrade now."""
    project = project_factory("base_with_auth_service")
    user = project / "app/models/user.py"
    user.write_text(user.read_text() + "\n\n# kept by the project\n")

    result = ManualUpdater(project).add_component(
        "auth", {"auth_level": "org"}, run_post_gen=False
    )

    assert result.success, result.error_message
    text = user.read_text()
    assert "role" in text
    assert "# kept by the project" in text
    assert (project / "app/services/auth/domains/orgs/organizations.py").exists()


def test_adding_evals_brings_the_harness(project_factory: ProjectFactory) -> None:
    project = project_factory("base_with_ai_sqlite_service")
    assert not (project / f"{AI}/domains/evals").exists()

    result = ManualUpdater(project).add_component(
        "ai", {"ai_evals": True}, run_post_gen=False
    )

    assert result.success, result.error_message
    assert (project / f"{AI}/domains/evals/runner.py").exists()
    # The run's tables, and what keeps a run in them, arrive with it.
    assert (project / f"{AI}/models/evals/run.py").exists()
    assert (project / f"{AI}/domains/evals/recorder.py").exists()
    assert (project / "evals/starter.yaml").exists()
    assert "evals" in (project / "pyproject.toml").read_text()
    # And the ways to run and read it: the CLI, the API, make.
    assert "import evals" in (project / "app/cli/ai/__init__.py").read_text()
    assert (project / "app/cli/ai/evals.py").exists()
    router = (project / "app/components/backend/api/ai/router.py").read_text()
    assert "evals.router" in router
    assert "eval_runs" in (project / f"{AI}/service/__init__.py").read_text()
    assert "evals-ci:" in (project / "Makefile").read_text()
    # The Overseer's Evals section needs the htmx frontend, which this lacks.
    assert not (project / EVALS_PAGE).exists()

    added = ManualUpdater(project).add_component("htmx", None, run_post_gen=False)

    assert added.success, added.error_message
    assert "evals_context" in (project / EVALS_PAGE).read_text()


def test_the_frontend_brings_no_evals_section_without_evals(
    project_factory: ProjectFactory,
) -> None:
    project = project_factory("base_with_ai_sqlite_service")

    result = ManualUpdater(project).add_component("htmx", None, run_post_gen=False)

    assert result.success, result.error_message
    page = project / EVALS_PAGE
    assert not page.exists() or not page.read_text().strip()


def test_adding_evals_to_a_langchain_project_is_refused(
    project_factory: ProjectFactory,
) -> None:
    project = project_factory("ai_langchain")

    result = ManualUpdater(project).add_component(
        "ai", {"ai_evals": True}, run_post_gen=False
    )

    assert not result.success
    assert "Pydantic AI" in (result.error_message or "")
    assert not (project / f"{AI}/domains/evals").exists()
