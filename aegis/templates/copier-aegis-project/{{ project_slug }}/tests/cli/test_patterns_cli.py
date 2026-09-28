"""``patterns``: the app's patterns and macro catalog, for an agent to read
before building. The same report the Overseer's Patterns page renders."""

import json
import subprocess
import sys
from typing import Any

from typer.testing import CliRunner

from app.cli.patterns import app
from app.services.system import patterns


def _run(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def _json() -> dict[str, Any]:
    return json.loads(_run("--format", "json"))


def test_json_carries_every_installed_pattern() -> None:
    keys = [p["key"] for p in _json()["patterns"]]
    assert keys == list(patterns.installed_patterns())


def test_json_rules_say_why_and_the_canonical_example_has_source() -> None:
    route = next(p for p in _json()["patterns"] if p["key"] == "route")
    assert route["rules"] and all(rule["why"] for rule in route["rules"])
    assert "def " in route["canonical"]["source"]
    assert route["canonical"]["file"].endswith(".py")


def test_markdown_reads_as_a_brief() -> None:
    out = _run()
    assert out.startswith("# Patterns")
    assert "## Route" in out
    assert "Lives in the API package" in out
    assert "```python" in out


def test_macros_come_with_the_web_frontend() -> None:
    try:
        from app.components.web_frontend import macro_catalog
    except ImportError:
        assert "macros" not in _json()
        return
    files = [group["file"] for group in _json()["macros"]]
    assert files == list(macro_catalog.FILES.values())


def test_the_real_command_prints_nothing_but_the_report() -> None:
    """Run as a program would: startup logging must not reach stdout."""
    run = subprocess.run(
        [sys.executable, "-m", "app.cli.main", "patterns", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(run.stdout)["patterns"]
