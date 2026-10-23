"""The conformance job finds Illiana's earlier comment by its marker,
written in ``pattern_review``, so a reworded one cannot leave CI posting
twice; and it posts every review she writes, her seal of approval on a
change with nothing new included."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
REVIEW = (
    ROOT
    / "aegis/templates/copier-aegis-project/{{ project_slug }}"
    / "app/services/system/pattern_review.py"
)
WORKFLOW = ROOT / ".github/workflows/stack-matrix.yml"


def _constant(name: str) -> str:
    found = re.search(rf'^{name} = "(.+)"$', REVIEW.read_text(), re.MULTILINE)
    assert found, name
    return found.group(1)


def test_the_workflow_finds_her_comment_by_its_marker() -> None:
    assert _constant("MARKER") in WORKFLOW.read_text()


def test_the_workflow_posts_her_seal_too() -> None:
    """Nothing in the job holds back a review by what it says."""
    assert _constant("SEAL") not in WORKFLOW.read_text()
