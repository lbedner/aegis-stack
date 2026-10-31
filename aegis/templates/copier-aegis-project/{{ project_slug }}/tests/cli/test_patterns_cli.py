"""``patterns``: the app's patterns and macro catalog, for an agent to read
before building. The same report the Overseer's Patterns page renders."""

import asyncio
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


def test_touches_says_what_a_change_reaches() -> None:
    """``patterns touches``: the parts a change's files are, as JSON alone
    (the brief is not printed with it)."""
    run = subprocess.run(
        [
            *(sys.executable, "-m", "app.cli.main", "patterns", "touches"),
            *("app/components/backend/main.py", "README.md", "--format", "json"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    found = json.loads(run.stdout)
    assert "component:backend" in found["parts"]
    assert found["elsewhere"] == ["README.md"]


def test_check_is_advisory_and_says_what_is_new() -> None:
    """``patterns check``: whatever the app's debt, it exits 0 unless
    ``--strict``, and ends with Illiana's verdict, the known debt beside
    it."""
    run = subprocess.run(
        [sys.executable, "-m", "app.cli.main", "patterns", "check"],
        capture_output=True,
        text=True,
        check=True,
    )
    last = run.stdout.splitlines()[-1]
    assert last.startswith(("Illiana: blocked.", "Illiana: clear."))
    assert " known in .patterns-baseline.json" in last


def _review_pr(
    monkeypatch: Any, comments: list[dict[str, Any]], said: str
) -> tuple[list[tuple[str, ...]], list[str]]:
    """``patterns review --pr 5`` on ``acme/app`` with ``comments`` on the
    pull request and ``said`` as her review: each ``gh api`` call, and the
    comment each review was given as the one before it."""
    from app.cli import patterns as cli
    from app.services.system.pattern_review import MARKER

    calls: list[tuple[str, ...]] = []
    given: list[str] = []

    def gh(*args: str, body: str | None = None) -> str:
        calls.append((*args, *([body] if body is not None else [])))
        if args[0].endswith("/comments") and "-X" not in args:
            # gh applies the filter; the one asked for selects by the marker.
            assert f"startswith({json.dumps(MARKER)})" in args[-1]
            ours = [c for c in comments if c["body"].startswith(MARKER)]
            return "".join(json.dumps([c["id"], c["body"]]) + "\n" for c in ours)
        return ""

    async def review(fresh: Any, touched: str, previous: str, commit: str) -> str:
        given.append(previous)
        return said

    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/app")
    monkeypatch.setattr(cli, "_writes", lambda: True)
    monkeypatch.setattr(cli, "_findings", lambda: [])
    monkeypatch.setattr(cli, "_gh", gh)
    monkeypatch.setattr(cli.pattern_review, "review", review)
    # The command is async: the app's CLI harness awaits it, CliRunner would not.
    asyncio.run(cli.review(changed=None, previous=None, commit="abc", pr=5))
    return calls, given


def test_review_on_a_pull_request_edits_her_comment(monkeypatch: Any) -> None:
    """Found by its marker, read as the reviews before this one, and edited
    in place: one comment per pull request."""
    from app.services.system.pattern_review import MARKER

    ours = {"id": 7, "body": f"{MARKER}\nbefore"}
    calls, given = _review_pr(
        monkeypatch, [{"id": 3, "body": "someone else"}, ours], "now"
    )

    assert given == [ours["body"]]
    assert calls[-1] == (
        "-X",
        "PATCH",
        "repos/acme/app/issues/comments/7",
        "--input",
        "-",
        json.dumps({"body": "now"}),
    )


def test_review_on_a_pull_request_posts_her_first_comment(monkeypatch: Any) -> None:
    calls, given = _review_pr(monkeypatch, [], "now")

    assert given == [""]
    assert calls[-1][:3] == ("-X", "POST", "repos/acme/app/issues/5/comments")


def test_a_review_with_nothing_to_say_posts_nothing(monkeypatch: Any) -> None:
    """The same findings an earlier review covered: no edit at all."""
    calls, _ = _review_pr(monkeypatch, [], "")

    assert all("-X" not in call for call in calls)
