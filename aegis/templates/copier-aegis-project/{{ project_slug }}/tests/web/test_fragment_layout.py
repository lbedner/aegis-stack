"""The fragment layout: what an htmx request gets instead of the shell.

Same ``app_content`` block as the shell, no chrome around it, so one page
template serves both render paths by switching which layout it extends.
"""

from app.components.web_frontend.rendering import templates
from tests.web.dom import none, one

PROBE = '<p id="probe">hello</p>'


def render_fragment(body: str = PROBE) -> str:
    template = templates.env.from_string(
        '{% extends "layouts/fragment.html" %}'
        "{% block app_content %}" + body + "{% endblock %}"
    )
    return template.render()


class TestFragmentLayout:
    def test_renders_the_child_block(self) -> None:
        one(render_fragment(), "#probe")

    def test_carries_no_shell_chrome(self) -> None:
        """Swapped into ``#app-content``, so a second sidebar, main or
        document skeleton would nest inside the live page."""
        fragment = render_fragment()
        for landmark in ("html", "head", "body", "aside", "nav", "main", "script"):
            none(fragment, landmark)

    def test_is_nothing_but_the_block(self) -> None:
        assert render_fragment().strip() == PROBE
