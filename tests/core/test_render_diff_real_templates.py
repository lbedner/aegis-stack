"""Integration check: the real aegis-stack templates carry the policy
annotations RD-02 (aegis-stack#917) ported off ``shared_files.py``.

Isolated from ``test_render_diff_policy.py``'s fixture-tree unit tests —
this is the "did the port actually land correctly on disk" check, run
against the live template tree via ``get_template_path()``.
"""

from __future__ import annotations

import pytest

from aegis.core.component_files import get_template_path
from aegis.core.render_diff import FilePolicy, RenderDiffEngine
from tests.core.conftest import make_render_diff_engine


@pytest.fixture
def engine(tmp_path) -> RenderDiffEngine:
    return make_render_diff_engine(get_template_path(), tmp_path)


USER_OWNED_FILES = (
    "README.md",
    "mkdocs.yml",
    "docs/api.md",
    "docs/development.md",
    "docs/health.md",
)

WARN_IF_DIVERGED_FILES = ("Dockerfile",)

NO_BACKUP_FILES = (
    "app/services/system/health_db.py",
    "app/services/system/health_db_sqlite.py",
    "app/services/system/health_db_postgres.py",
    "app/components/backend/startup/database_init.py",
)


class TestRealTemplatesCarryTheirPolicy:
    @pytest.mark.parametrize("rel_path", USER_OWNED_FILES)
    def test_user_owned(self, engine: RenderDiffEngine, rel_path: str) -> None:
        assert engine.policy_for(rel_path) == FilePolicy.USER_OWNED

    @pytest.mark.parametrize("rel_path", WARN_IF_DIVERGED_FILES)
    def test_warn_if_diverged(self, engine: RenderDiffEngine, rel_path: str) -> None:
        assert engine.policy_for(rel_path) == FilePolicy.WARN_IF_DIVERGED

    @pytest.mark.parametrize("rel_path", NO_BACKUP_FILES)
    def test_no_backup(self, engine: RenderDiffEngine, rel_path: str) -> None:
        assert engine.policy_for(rel_path) == FilePolicy.NO_BACKUP

    @pytest.mark.parametrize(
        "rel_path", USER_OWNED_FILES + WARN_IF_DIVERGED_FILES + NO_BACKUP_FILES
    )
    def test_annotation_never_leaks_into_rendered_content(
        self, engine: RenderDiffEngine, rel_path: str
    ) -> None:
        content = engine._render(
            rel_path,
            {
                "project_name": "demo",
                "project_description": "A demo.",
                "author_name": "A",
                "include_htmx": True,
                "python_version": "3.13",
                "database_engine": "postgres",
            },
        )
        assert "aegis:" not in content

    def test_dockerignore_is_static_and_needs_no_annotation(
        self, engine: RenderDiffEngine
    ) -> None:
        """``.dockerignore`` has no ``.jinja`` extension and no template
        markers — it never varies with answers, so under the render-diff
        design BASE always equals OURS and the old no-backup policy is
        unreachable. Documents the decision not to force a pointless
        ``.jinja`` conversion (see RD-02 ticket body)."""
        assert engine.policy_for(".dockerignore") == FilePolicy.DEFAULT
        a = engine._render(".dockerignore", {"include_htmx": True})
        b = engine._render(".dockerignore", {"include_htmx": False})
        assert a == b
