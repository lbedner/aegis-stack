"""Shared helpers for tests/core.

The render-diff suites (test_render_diff*.py) each build small fixture
template trees and engines; the construction boilerplate lives here once.
"""

from __future__ import annotations

from pathlib import Path

from aegis.core.render_diff import RenderDiffEngine, build_template_env


def write_template_file(path: Path, content: str) -> None:
    """Write ``content`` to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_render_diff_engine(template_root: Path, tmp_path: Path) -> RenderDiffEngine:
    """An engine over ``template_root`` with a fresh project dir under
    ``tmp_path``, using the production env semantics (build_template_env)."""
    project_path = tmp_path / "project"
    project_path.mkdir(exist_ok=True)
    return RenderDiffEngine(
        jinja_env=build_template_env(template_root),
        template_root=template_root,
        project_path=project_path,
    )
