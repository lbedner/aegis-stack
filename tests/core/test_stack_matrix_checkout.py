"""Stack Matrix fetches the repo from GitHub once per run, not once per job:
GitHub counts every checkout as a clone, and ~40 jobs a push buried the
real clones under CI's. ``changes`` checks out and hands the rest a copy."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/stack-matrix.yml"
# ``changes`` diffs against the base branch and ``conformance`` (Illiana)
# generates it: both need the history, which the copy leaves out.
FETCHERS = {"changes", "conformance"}


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return jobs


def _uses(job: dict[str, Any]) -> list[str]:
    return [step.get("uses", "").split("@")[0] for step in job["steps"]]


def test_only_the_jobs_that_need_history_fetch_from_github() -> None:
    fetching = {
        name for name, job in _jobs().items() if "actions/checkout" in _uses(job)
    }
    assert fetching == FETCHERS


def test_every_other_job_starts_from_the_copy_changes_uploads() -> None:
    jobs = _jobs()
    upload = next(
        s for s in jobs["changes"]["steps"] if "upload-artifact" in s.get("uses", "")
    )
    for name, job in jobs.items():
        if name in FETCHERS:
            continue
        assert job["needs"] == "changes", name
        first, unpack = job["steps"][:2]
        assert "download-artifact" in first["uses"], name
        assert first["with"]["name"] == upload["with"]["name"], name
        assert "tar -xf" in unpack["run"], name
