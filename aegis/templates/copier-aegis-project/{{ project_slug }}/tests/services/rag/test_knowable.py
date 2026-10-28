"""What of this app a knowledge base can know (``rag.knowable``), over this
project: each part with its files the loader reads, by extension and how
big, the file types found grouped by what they are, and the files a pick
of parts and types reads (any kind of file a part owns, never its tests
or another part's)."""

import pytest

from app.core import source_index
from app.core.ontology.model import Category, Kind, PartNode
from app.services.rag import knowable
from tests._ontology import model_of

AI = PartNode(kind=Kind.SERVICE, name="ai", category=Category.APP)
RAG = PartNode(kind=Kind.SERVICE, name="ai.rag", category=Category.APP, owner=AI.id)


@pytest.fixture(autouse=True)
def twin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowable, "current", lambda: model_of([AI, RAG], []))


def test_each_part_says_what_it_holds_by_file_type() -> None:
    found = knowable.knowable()

    group, picks = found.parts[0]
    assert (group, [pick for pick, *_ in picks]) == ("Services", [AI.id])
    files, size = found.held[AI.id][".py"]
    assert files > 1 and size > files
    assert ".py" in dict(found.types)["Code"]
    assert ".py" in found.ticked


def test_a_pick_reads_its_parts_files_of_the_types_ticked() -> None:
    code = knowable.paths_of([AI.id], [".py"])

    root = str(source_index.ROOT / "app")
    assert str(source_index.ROOT / "app/services/rag/knowable.py") in code
    assert all(p.startswith(root) and p.endswith(".py") for p in code)
    assert knowable.paths_of([AI.id], [".nothing"]) == []


def test_what_is_left_out_is_never_read() -> None:
    """``exclude`` globs, in place of the loader's own, as a folder's are."""
    rest = knowable.paths_of([AI.id], [".py"], ["**/rag/**"])

    assert rest and not [p for p in rest if "/rag/" in p]
