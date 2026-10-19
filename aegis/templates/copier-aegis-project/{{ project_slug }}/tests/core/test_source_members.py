"""A class's members read from its source (``source_members``): the
methods it defines or inherits from the project's own bases, the class each
attribute is given, and which classes are tables."""

from pathlib import Path

import pytest

from app.core import source_index
from app.core.source_members import Source
from tests._files import write_tree

SERVICE = "app.services.blog.service"
FILES = {
    "app/__init__.py": "",
    "app/services/__init__.py": "",
    "app/services/blog/__init__.py": "",
    "app/services/blog/base.py": (
        "class Base:\n    def shared(self) -> None:\n        return None\n"
    ),
    "app/services/blog/store.py": (
        "class Store:\n    def put(self) -> None:\n        return None\n"
    ),
    "app/services/blog/service.py": (
        "from sqlmodel.ext.asyncio.session import AsyncSession\n"
        "from app.services.blog.base import Base\n"
        "from app.services.blog.store import Store\n"
        "class BlogService(Base):\n"
        "    log: 'Store'\n"
        "    def __init__(self, db: AsyncSession, store: Store | None) -> None:\n"
        "        self.db = db\n"
        "        self.store = store\n"
        "    async def get(self) -> None:\n"
        "        return None\n"
        "    @property\n"
        "    def backup(self) -> Store:\n"
        "        return Store()\n"
    ),
    "app/services/blog/models.py": (
        "from sqlmodel import SQLModel\n"
        "class Post(SQLModel, table=True):\n"
        '    __tablename__ = "blog_post"\n'
        "class Tag(SQLModel, table=True):\n"
        "    name: str\n"
        "class PostCreate(SQLModel):\n"
        "    title: str\n"
    ),
}


@pytest.fixture
def source(tmp_path: Path) -> Source:
    write_tree(tmp_path, FILES)
    return Source(source_index.at(tmp_path))


def test_a_method_is_the_classes_own_or_a_project_bases(source: Source) -> None:
    service = (SERVICE, "BlogService")
    assert source.method(service, "get") == (SERVICE, "BlogService.get")
    assert source.method(service, "shared") == ("app.services.blog.base", "Base.shared")
    assert source.method(service, "missing") is None


def test_an_attribute_has_the_class_it_is_given(source: Source) -> None:
    """In ``__init__`` from an annotated parameter kept on ``self``,
    annotated in the class body, or a property's return; a library's class
    is not followed."""
    service = (SERVICE, "BlogService")
    store = ("app.services.blog.store", "Store")
    assert source.attribute(service, "store") == store
    assert source.attribute(service, "log") == store
    assert source.attribute(service, "backup") == store
    assert source.attribute(service, "db") is None


def test_a_table_is_a_class_marked_table_by_its_name(source: Source) -> None:
    models = "app.services.blog.models"
    assert source.table((models, "Post")) == "blog_post"
    assert source.table((models, "Tag")) == "tag"
    assert source.table((models, "PostCreate")) is None


def test_a_definition_is_found_by_its_qualified_name(source: Source) -> None:
    found = source.definition((SERVICE, "BlogService.get"))
    assert found is not None and found.lineno == 9
    assert source.definition((SERVICE, "BlogService.nothing")) is None
