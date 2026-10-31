"""A generated project's pull requests get Illiana's review in CI, as
aegis-stack's own do (the ``conformance`` job of stack-matrix.yml): the new
``patterns check`` findings, annotated, her comment from ``patterns review``,
and her verdict last.
"""

from __future__ import annotations

from typing import Any

from tests.core.test_generated_ci_parallel import _ci


def _job(**overrides: object) -> dict[str, Any]:
    return _ci(**overrides)["jobs"]["illiana"]


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in job["steps"] if s.get("name") == name)


def test_illiana_reviews_pull_requests_only() -> None:
    job = _job()

    assert job["name"] == "Illiana"
    assert job["if"] == "github.event_name == 'pull_request'"
    assert job["permissions"]["pull-requests"] == "write"
    # A hung model call ends; two pushes never post two comments.
    assert job["timeout-minutes"] == 20
    assert job["concurrency"] == {
        "group": "illiana-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


def test_the_known_debt_is_the_base_branchs_own() -> None:
    """A change cannot hide its findings by adding them to the baseline it
    carries: the base branch's code gives the known debt, checked with this
    branch's environment."""
    run = _step(_job(), "Known debt, from the base branch")["run"]

    assert 'git worktree add "$RUNNER_TEMP/base" "origin/${{ github.base_ref }}"' in run
    assert (
        '"$GITHUB_WORKSPACE/.venv/bin/python" -m app.cli.main patterns check --update'
        in run
    )
    assert 'cp "$RUNNER_TEMP/base/.patterns-baseline.json" .' in run


def test_new_findings_are_checked_strict_and_the_verdict_comes_last() -> None:
    """Her comment posts before a blocking finding fails the job, and only
    a repository that asked for it (``ILLIANA_BLOCKS``) is ever failed."""
    job = _job()
    run = _step(job, "New findings, annotated")["run"]

    assert 'patterns check --strict "${changed[@]}"' in run
    assert job["steps"][-1] == {
        "name": "Illiana's verdict",
        "if": "vars.ILLIANA_BLOCKS == 'true'",
        "run": 'exit "${{ steps.findings.outputs.code }}"',
    }


AI = {"include_ai": True, "ai_framework": "pydantic-ai", "ai_backend": "sqlite"}


def test_her_comment_posts_as_her_app_where_it_is_set() -> None:
    job = _job(**AI)
    review = _step(job, "Illiana's review, on the pull request")

    token = _step(job, "Illiana's token")
    assert token["if"] == "steps.key.outputs.app == 'true'"
    # A bad key or an app not installed: the bot posts, nothing fails.
    assert token["continue-on-error"] is True
    assert review["continue-on-error"] is True
    assert review["env"]["GH_TOKEN"] == (
        "${{ steps.app.outputs.token || github.token }}"
    )
    assert "patterns review" in review["run"] and "--pr " in review["run"]
    # The model only on ``ILLIANA_REVIEW=model``: a key alone turns nothing on.
    assert review["env"]["OPENAI_API_KEY"] == (
        "${{ vars.ILLIANA_REVIEW == 'model' && secrets.OPENAI_API_KEY || '' }}"
    )
    # Her agent row is only read for the write-up.
    assert '[ -n "$OPENAI_API_KEY" ]' in review["run"]
    assert "alembic -c alembic/alembic.ini upgrade head" in review["run"]


def test_without_her_writer_the_check_runs_alone() -> None:
    """``patterns review`` needs the AI service on PydanticAI with a
    database; without it the findings and the verdict still run."""
    for answers in ({}, {**AI, "ai_backend": "memory"}):
        names = [s.get("name") for s in _job(**answers)["steps"]]
        assert "New findings, annotated" in names
        assert "Illiana's review, on the pull request" not in names


def test_her_review_reads_a_database_as_the_app_does() -> None:
    """Her agent row and spend are rows: a Postgres project gets a Postgres
    service the review reaches as the CLI does (``DATABASE_URL_LOCAL``);
    SQLite needs none."""
    postgres = _job(
        **{**AI, "ai_backend": "postgres"},
        include_database=True,
        database_engine="postgres",
    )
    assert postgres["services"]["postgres"]["image"] == "postgres:16-alpine"
    assert postgres["env"]["DATABASE_URL_LOCAL"] == (
        "postgresql://postgres:postgres@localhost:5432/demo"
    )
    assert "services" not in _job(**AI, include_database=True)
