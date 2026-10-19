"""The conformance job finds Illiana's earlier comment by its marker, and
skips posting a review with nothing new by its text: both written in
``pattern_review``, so a reworded one cannot leave CI posting twice."""

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


def test_the_workflow_reads_the_reviews_own_words() -> None:
    workflow = WORKFLOW.read_text()
    assert _constant("MARKER") in workflow
    assert _constant("NOTHING") in workflow
