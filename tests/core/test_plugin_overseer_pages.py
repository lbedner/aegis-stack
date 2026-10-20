"""
A plugin's own page on the htmx Overseer (``PluginWiring.overseer_pages``).

``overseer_sections.py`` registers the page at the plugin's entry in the
rail, the way each in-tree page is; it re-renders when a plugin comes or
goes.
"""

from __future__ import annotations

import ast

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_template_path
from aegis.core.plugins.composer import PLUGINS_ANSWER_KEY, serialize_plugin_to_answer
from aegis.core.plugins.spec import (
    OverseerPageWiring,
    PluginKind,
    PluginSpec,
    PluginWiring,
)

SECTIONS = "{{ project_slug }}/app/components/web_frontend/overseer_sections.py.jinja"

CRAWLER = OverseerPageWiring(
    name="crawler",
    module="app.components.web_frontend.overseer_crawler",
    folder="crawler",
)


def _render(plugins: list[dict]) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    return env.get_template(SECTIONS).render({PLUGINS_ANSWER_KEY: plugins})


def _plugin(*pages: OverseerPageWiring) -> dict:
    spec = PluginSpec(
        name="crawl4ai",
        kind=PluginKind.SERVICE,
        description="x",
        verified=False,
        wiring=PluginWiring(overseer_pages=list(pages)),
    )
    return serialize_plugin_to_answer(spec)


def test_sections_register_the_plugin_page() -> None:
    out = _render([_plugin(CRAWLER)])
    ast.parse(out)
    assert "import app.components.web_frontend.overseer_crawler as crawler_page" in out
    assert 'pages[("services", "crawler")] = SectionedPage(' in out
    assert '"crawler", crawler_page.SECTIONS, crawler_page.section_context' in out


def test_a_component_plugin_page_lands_under_components() -> None:
    page = OverseerPageWiring(
        name="vault", module="app.x.overseer_vault", folder="vault", group="components"
    )
    assert 'pages[("components", "vault")]' in _render([_plugin(page)])


def test_older_answers_render_as_no_plugins() -> None:
    """An answers file written before the field has no ``overseer_pages``."""
    older = _plugin()
    del older["wiring"]["overseer_pages"]
    assert _render([older]) == _render([])
    assert "_page." not in _render([])
