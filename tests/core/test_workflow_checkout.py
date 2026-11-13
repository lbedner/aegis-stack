"""CI and Stack Matrix fetch the repo from GitHub once per run, not once per
job: GitHub counts every checkout as a clone, and a run's jobs buried the
real clones under CI's. One job checks out and hands the rest a copy."""

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[2] / ".github/workflows"

# Per workflow: the job that uploads the copy, the jobs that fetch from GitHub
# themselves, and the jobs that run no repo code at all.
HANDOFFS = {
    # ``changes`` diffs against the base branch and ``conformance`` (Illiana)
    # generates it: both need the history, which the copy leaves out.
    "stack-matrix.yml": ("changes", {"changes", "conformance"}, set()),
    # ``test`` only collects the shards' results.
    "ci.yml": ("repo", {"repo"}, {"test"}),
}


def _workflow(name: str) -> dict[str, Any]:
    workflow: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
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


@pytest.mark.parametrize("name", ["ci.yml", "security.yml"])
def test_a_new_push_to_a_pr_cancels_its_older_run(name: str) -> None:
    """A rebased PR re-runs everything; the run it replaces stops instead of
    cloning on. Main's runs never cancel: every merge is tested."""
    concurrency = _workflow(name)["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )
