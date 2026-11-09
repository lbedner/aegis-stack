"""A generated project scores its evals in CI once it names a model.

The job is opt-in (``vars.AI_MODEL``), its runner configurable
(``vars.EVALS_RUNNER``) so a self-hosted runner can reach a local Ollama,
and it is handed the key of every installed provider.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.core.test_generated_ci_parallel import _ci

ROOT = Path(__file__).parents[2]

EVALS = {"include_ai": True, "ai_evals": True, "ai_backend": "sqlite"}


def _jobs(**overrides: object) -> dict:
    return _ci(**overrides)["jobs"]


def test_the_evals_run_once_a_model_is_named() -> None:
    job = _jobs(**EVALS, ai_providers="openai,groq,openrouter,ollama")["evals"]

    # A fork's pull request gets no secrets, and a failing suite no run.
    assert job["if"] == (
        "vars.AI_MODEL != '' && (github.event_name == 'push'"
        " || github.event.pull_request.head.repo.full_name == github.repository)"
    )
    assert job["needs"] == ["test"]
    assert job["runs-on"] == "${{ vars.EVALS_RUNNER || 'ubuntu-latest' }}"
    assert job["env"]["AI_MODEL"] == "${{ vars.AI_MODEL }}"
    assert job["env"]["AI_PROVIDER"] == "${{ vars.AI_PROVIDER || 'openai' }}"
    keys = {name for name in job["env"] if name.endswith("_API_KEY")}
    assert keys == {"OPENAI_API_KEY", "GROQ_API_KEY", "OPEN_ROUTER_API_KEY"}
    assert job["env"]["OLLAMA_BASE_URL_LOCAL"] == "${{ vars.OLLAMA_BASE_URL }}"
    assert "ai evals run" in job["steps"][-1]["run"]


def test_a_postgres_stack_gets_its_database() -> None:
    job = _jobs(**EVALS, include_database=True, database_engine="postgres")["evals"]

    assert job["services"]["postgres"]["image"] == "postgres:16-alpine"
    assert job["env"]["DATABASE_URL_LOCAL"].startswith("postgresql://")


def test_no_job_without_evals_a_model_can_score() -> None:
    assert "evals" not in _jobs(include_ai=True)
    assert "evals" not in _jobs(**{**EVALS, "ai_backend": "memory"})


def test_the_framework_scores_the_evals_stack_on_a_real_model() -> None:
    """Advisory: a model's off day never holds a framework pull request."""
    workflow = ROOT / ".github/workflows/stack-matrix.yml"
    job = yaml.safe_load(workflow.read_text())["jobs"]["evals"]

    assert job["continue-on-error"] is True
    score = job["steps"][-1]
    # Without the key (a fork, Dependabot) nothing is generated.
    assert job["steps"][-2]["if"] == score["if"] == "steps.key.outputs.key == 'yes'"
    assert score["env"]["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    assert "generate_stack.sh ai_evals" in job["steps"][-2]["run"]
    assert "ai evals run" in score["run"]
