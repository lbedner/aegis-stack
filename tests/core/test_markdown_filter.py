"""The markdown filter ships and is wired.

Its behaviour - real GFM, raw HTML escaped - is tested inside a generated
project (``tests/web/test_filters.py``), where marko is installed. These are
the structural checks that can run here: the dependency is pinned, the file
ships, and the filter is registered rather than left for each template to
re-implement.
"""

from __future__ import annotations

from pathlib import Path

from aegis.core.component_files import get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
FILTERS = "app/components/web_frontend/filters.py"


def _dependencies(**overrides: object) -> list[str]:
    import tomllib

    from jinja2 import Environment, FileSystemLoader

    from aegis.core.component_files import get_copier_defaults

    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    ctx = {**get_copier_defaults(), "project_slug": "demo_app", **overrides}
    rendered = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/pyproject.toml.jinja"
    ).render(ctx)
    return tomllib.loads(rendered)["project"]["dependencies"]


def test_marko_ships_wherever_the_filter_does() -> None:
    """The filter imports marko at module import, and it lives in the web
    frontend. A project with htmx and no AI got neither the pin nor a
    working templates module: every htmx stack in the matrix died on
    ``ModuleNotFoundError: No module named 'marko'``.
    """
    for overrides in (
        {"include_htmx": True, "include_ai": False},
        {"include_htmx": True, "include_ai": True},
        {"include_htmx": False, "include_ai": True},
    ):
        deps = _dependencies(**overrides)

        assert sum("marko" in dep for dep in deps) == 1, overrides


def test_it_is_not_pinned_where_nothing_renders_markdown() -> None:
    """No frontend and no AI is no renderer; a dependency nobody imports
    is weight."""
    deps = _dependencies(include_htmx=False, include_ai=False)

    assert not any("marko" in dep for dep in deps)


def test_the_filter_file_is_not_jinja_gated_away() -> None:
    """It ships with the web frontend; a project without one removes the
    file wholesale rather than rendering it empty."""
    path = get_template_path() / PROJECT_SLUG_PLACEHOLDER / FILTERS

    assert Path(path).exists()


def test_the_filter_is_registered_for_templates() -> None:
    """Registered once, or every template writes its own escaping."""
    source = (get_template_path() / PROJECT_SLUG_PLACEHOLDER / FILTERS).read_text()

    assert '"markdown": markdown' in source
    assert "PROSE_CLASSES" in source
