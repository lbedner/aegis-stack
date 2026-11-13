"""CI and Stack Matrix fetch the repo from GitHub once per run, not once per
job: GitHub counts every checkout as a clone, and a run's jobs buried the
real clones under CI's. One job checks out and hands the rest a copy. The
CI a generated project ships with does the same, so a project's own traffic
page is not its CI either."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.core.test_dev_deps_one_mechanism import _render

WORKFLOWS = Path(__file__).parents[2] / ".github/workflows"

# Per workflow: the job that uploads the copy, the jobs that fetch from GitHub
# themselves, and the jobs that run no repo code at all.
HANDOFFS = {
    # ``conformance`` (Illiana) generates the base branch too, and needs the
    # history the copy leaves out.
    "stack-matrix.yml": ("changes", {"changes", "conformance"}, set()),
    # ``test`` only collects the shards' results.
    "ci.yml": ("repo", {"repo"}, {"test"}),
    # The publish jobs upload what ``build`` built and read no repo.
    "release.yml": ("build", {"build"}, {"publish-testpypi", "publish-pypi"}),
    # A generated project's CI. ``illiana`` checks the base branch too.
    "generated": ("repo", {"repo", "illiana"}, {"test"}),
    "generated, with evals": ("repo", {"repo", "illiana"}, {"test"}),
}

# The answers each generated workflow above is rendered with.
GENERATED: dict[str, dict[str, object]] = {
    "generated": {},
    "generated, with evals": {
        "include_ai": True,
        "include_database": True,
        "ai_backend": "sqlite",
        "ai_evals": True,
    },
}
# The workflows that run on every push to a pull request.
ON_EVERY_PUSH = ["ci.yml", "generated"]


def _workflow(name: str) -> dict[Any, Any]:
    # Not ``str`` keys: PyYAML reads the bare ``on`` key as the boolean True.
    if name in GENERATED:
        text = _render(".github/workflows/ci.yml.jinja", **GENERATED[name])
    else:
        text = (WORKFLOWS / name).read_text()
    workflow: dict[Any, Any] = yaml.safe_load(text)
    return workflow


def _uses(job: dict[str, Any]) -> list[str]:
    return [step.get("uses", "").split("@")[0] for step in job["steps"]]


@pytest.mark.parametrize("name", HANDOFFS)
def test_only_the_handoff_jobs_fetch_from_github(name: str) -> None:
    jobs = _workflow(name)["jobs"]
    fetching = {job for job, spec in jobs.items() if "actions/checkout" in _uses(spec)}
    assert fetching == HANDOFFS[name][1]


@pytest.mark.parametrize("name", HANDOFFS)
def test_every_other_job_starts_from_the_uploaded_copy(name: str) -> None:
    uploader, fetchers, repo_free = HANDOFFS[name]
    jobs = _workflow(name)["jobs"]
    upload = next(
        s for s in jobs[uploader]["steps"] if "upload-artifact" in s.get("uses", "")
    )
    for job, spec in jobs.items():
        if job in fetchers | repo_free:
            continue
        needs = spec["needs"]
        assert uploader in ([needs] if isinstance(needs, str) else needs), job
        first, unpack = spec["steps"][:2]
        assert "download-artifact" in first["uses"], job
        assert first["with"]["name"] == upload["with"]["name"], job
        assert "tar -xf" in unpack["run"], job


@pytest.mark.parametrize("name", ON_EVERY_PUSH)
def test_a_new_push_to_a_pr_cancels_its_older_run(name: str) -> None:
    """A rebased PR re-runs everything; the run it replaces stops instead of
    cloning on. Main's runs never cancel: every merge is tested."""
    concurrency = _workflow(name)["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )


@pytest.mark.parametrize("name", ON_EVERY_PUSH)
def test_the_security_jobs_ride_ci_s_one_checkout(name: str) -> None:
    """A workflow of their own was a second and third clone on every push.
    As CI jobs, the handoff tests above hold them to the shared copy; their
    names are required checks on main."""
    names = {job.get("name") for job in _workflow(name)["jobs"].values()}
    # A generated project ships CodeQL alone.
    audit = {"Security Audit"} if name == "ci.yml" else set()
    assert {"CodeQL Analysis"} | audit <= names


def test_docs_deploy_only_when_what_the_site_is_built_from_changed() -> None:
    paths = set(_workflow("docs.yml")[True]["push"]["paths"])
    # The two a filter on ``docs/**`` alone would miss: scripts/gen_docs.py
    # builds the home page from README.md.
    assert {"docs/**", "scripts/gen_docs.py", "README.md"} <= paths


def test_a_pr_that_runs_no_stacks_does_not_clone_to_find_that_out() -> None:
    """Most PRs touch no stack path. Which files a PR changed is asked of
    the API; the fetch happens only when there are stacks to hand it to."""
    steps = _workflow("stack-matrix.yml")["jobs"]["changes"]["steps"]
    checkout = next(s for s in steps if "actions/checkout" in s.get("uses", ""))
    assert checkout["if"] == "steps.paths.outputs.stack == 'true'"


def test_the_nightly_run_keeps_the_published_wheel_it_installed() -> None:
    """tests/integration/test_upgrade_matrix.py installs a released
    aegis-stack from PyPI. A pruned cache drops downloaded wheels, so every
    night fetched it again and counted as an install."""
    steps = _workflow("slow-suites.yml")["jobs"]["slow"]["steps"]
    uv = next(s for s in steps if "setup-uv" in s.get("uses", ""))["with"]
    assert uv["enable-cache"] is True
    assert uv["prune-cache"] is False
    # Its own key: CI's pruned cache for the same lockfile must not win.
    assert uv["cache-suffix"]
