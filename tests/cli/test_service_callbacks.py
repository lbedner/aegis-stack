"""Characterization tests for ``validate_and_resolve_services``.

Pin the bracket-syntax handling in ``aegis/cli/callbacks.py`` before (and
after) collapsing the three per-service parse blocks into a handler
registry: stored config side-effects, echo content, and per-service error
messages must not change. Echo *order* across services is deliberately not
pinned — it follows user input order after the collapse.
"""

from __future__ import annotations

from typing import Any

import pytest
import typer

from aegis.cli.callbacks import validate_and_resolve_services
from aegis.cli.interactive import (
    clear_all_ai_selections,
    get_auth_level_selection,
)


class _Ctx:
    """Minimal stand-in for typer.Context in callback signature."""

    resilient_parsing = False


@pytest.fixture(autouse=True)
def _reset_selections() -> Any:
    clear_all_ai_selections()
    yield
    clear_all_ai_selections()


def _run(value: str) -> list[str] | None:
    return validate_and_resolve_services(_Ctx(), None, value)  # type: ignore[arg-type]


class TestBracketParsing:
    def test_ai_options_stored_and_echoed(self, capsys: pytest.CaptureFixture) -> None:
        result = _run("ai[langchain,sqlite,openai]")
        assert result == ["ai[langchain,sqlite,openai]"]
        out = capsys.readouterr().out
        assert "AI service: framework=langchain" in out
        assert "backend=sqlite" in out
        assert "providers=openai" in out

    def test_auth_level_stored_and_echoed(self, capsys: pytest.CaptureFixture) -> None:
        result = _run("auth[rbac]")
        assert result == ["auth[rbac]"]
        assert get_auth_level_selection("auth") == "rbac"
        assert "Auth service: level=rbac" in capsys.readouterr().out

    def test_insights_sources_echoed(self, capsys: pytest.CaptureFixture) -> None:
        result = _run("insights[github,reddit]")
        assert result == ["insights[github,reddit]"]
        assert "Insights service: sources=github,reddit" in capsys.readouterr().out

    def test_mixed_services_all_handled(self, capsys: pytest.CaptureFixture) -> None:
        result = _run("auth[rbac],ai[langchain,sqlite,openai]")
        assert result == ["auth[rbac]", "ai[langchain,sqlite,openai]"]
        out = capsys.readouterr().out
        assert "AI service: framework=langchain" in out
        assert "Auth service: level=rbac" in out

    def test_plain_services_pass_through(self) -> None:
        assert _run("auth,ai") == ["auth", "ai"]


class TestBracketErrors:
    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("ai[bogus-framework]", "Invalid ai service syntax"),
            ("auth[bogus-level]", "Invalid auth service syntax"),
            ("insights[bogus-source]", "Invalid insights service syntax"),
        ],
    )
    def test_invalid_options_exit_with_service_message(
        self, value: str, message: str, capsys: pytest.CaptureFixture
    ) -> None:
        with pytest.raises(typer.Exit) as excinfo:
            _run(value)
        assert excinfo.value.exit_code == 1
        assert message in capsys.readouterr().err

    def test_unknown_service_lists_available(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        with pytest.raises(typer.Exit):
            _run("nonexistent")
        assert "Available services" in capsys.readouterr().err
