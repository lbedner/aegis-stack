"""Tests for the end-of-init replay command hint.

``aegis init`` prints the uvx one-liner that reproduces the just-built
stack non-interactively. The selections carry bracket syntax, so the
printed command must round-trip through the ``--components``/``--services``
parsers unchanged.
"""

from __future__ import annotations

from aegis.core.selection import build_replay_command


class TestBuildReplayCommand:
    def test_base_project(self) -> None:
        assert (
            build_replay_command("my-app", [], [])
            == "uvx aegis-stack init my-app --no-interactive"
        )

    def test_core_components_dropped(self) -> None:
        # backend/frontend ship in every project; replaying them is noise.
        cmd = build_replay_command("my-app", ["backend", "frontend", "redis"], [])
        assert (
            cmd == 'uvx aegis-stack init my-app --components "redis" --no-interactive'
        )

    def test_brackets_preserved(self) -> None:
        cmd = build_replay_command(
            "demo",
            ["redis", "worker[taskiq]", "scheduler[postgres]", "database[postgres]"],
            ["auth[rbac]", "ai[memory,pydantic-ai,public,rag]"],
        )
        assert cmd == (
            "uvx aegis-stack init demo "
            '--components "redis,worker[taskiq],scheduler[postgres],database[postgres]" '
            '--services "auth[rbac],ai[memory,pydantic-ai,public,rag]" '
            "--no-interactive"
        )

    def test_services_only(self) -> None:
        cmd = build_replay_command("demo", ["backend"], ["blog"])
        assert cmd == 'uvx aegis-stack init demo --services "blog" --no-interactive'

    def test_base_name_dupes_prefer_bracketed(self) -> None:
        # Service resolution can contribute a plain twin of a bracketed
        # selection (database vs database[postgres]); the replay must name
        # each component once, keeping the configured form.
        cmd = build_replay_command(
            "demo",
            ["scheduler[postgres]", "database", "database[postgres]", "scheduler"],
            [],
        )
        assert cmd == (
            "uvx aegis-stack init demo "
            '--components "scheduler[postgres],database[postgres]" --no-interactive'
        )

    def test_brackets_survive_rich_printing(self) -> None:
        # Regression: the hint is printed via rich; interpolating the command
        # into markup swallowed [taskiq]/[org] as style tags. Render the way
        # init does and assert the brackets reach the terminal.
        from rich.console import Console
        from rich.text import Text

        cmd = build_replay_command("demo", ["worker[taskiq]"], ["auth[org]"])
        console = Console(record=True, width=200, highlight=False)
        console.print(Text(f"   {cmd}", style="#17CCBF"))
        out = console.export_text()
        assert "worker[taskiq]" in out
        assert "auth[org]" in out
