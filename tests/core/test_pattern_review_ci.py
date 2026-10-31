"""Both workflows that post Illiana's review (aegis-stack's conformance job
and a generated project's ``illiana`` job) leave her comment to
``patterns review --pr``: it finds the comment by its marker, written once
in ``pattern_review``, so a reworded one cannot leave CI posting twice; and
nothing in a workflow holds back a review by what it says, her seal of
approval on a change with nothing new included."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "aegis/templates/copier-aegis-project/{{ project_slug }}"
REVIEW = TEMPLATE / "app/services/system/pattern_review.py"
WORKFLOWS = [
    ROOT / ".github/workflows/stack-matrix.yml",
    TEMPLATE / ".github/workflows/ci.yml.jinja",
]


def _constant(name: str) -> str:
    found = re.search(rf'^{name} = "(.+)"$', REVIEW.read_text(), re.MULTILINE)
    assert found, name
    return found.group(1)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_the_workflow_leaves_her_comment_to_the_command(workflow: Path) -> None:
    text = workflow.read_text()
    assert "patterns review" in text and "--pr " in text
    assert _constant("MARKER") not in text


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_the_workflow_posts_her_seal_too(workflow: Path) -> None:
    """Nothing in the job holds back a review by what it says."""
    assert _constant("SEAL") not in workflow.read_text()
