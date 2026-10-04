"""The Overseer Patterns page: the backend's patterns detected from the
running app, and the frontend's macros rendered beside their calls."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2.runtime import Macro
import pytest

from app.components.web_frontend import macro_catalog, overseer_patterns
from app.components.web_frontend.rendering import templates
from app.services.system.models import ComponentStatus
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    backend = ComponentStatus(name="backend", message="Running")
    sign_in(app, monkeypatch, status_with(backend))
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "") -> str:
    response = client.get("/overseer/patterns" + (f"/{section}" if section else ""))
    assert response.status_code == 200
    return response.text


def _public_macros(path: str) -> set[str]:
    module = templates.env.get_template(path).module
    return {
        name
        for name in dir(module)
        if not name.startswith("_") and isinstance(getattr(module, name), Macro)
    }


class TestNavigation:
    def test_patterns_sits_under_overview_in_the_sidebar(
        self, client: TestClient
    ) -> None:
        links = [text(a) for a in select(_get(client), "#overseer-nav a")]
        assert links[:2] == ["Overview", "Patterns"]

    def test_backend_patterns_then_frontend_macros(self, client: TestClient) -> None:
        subnav = one(_get(client), "#overseer-subnav")
        assert [text(h) for h in select(subnav, "h3")] == ["Backend", "Frontend"]
        backend = [p.title for p in overseer_patterns.PATTERNS.values()]
        assert [text(a) for a in select(subnav, "nav a")] == [
            *backend,
            "Layout",
            "Feedback",
            "Forms",
            "Tables",
        ]

    def test_unknown_section_is_404(self, client: TestClient) -> None:
        assert client.get("/overseer/patterns/nope").status_code == 404


class TestRoutePattern:
    def test_the_diagram_walks_a_request_through_with_counts(
        self, client: TestClient
    ) -> None:
        steps = select(_get(client), "#pattern-steps [data-step]")
        assert text(one(steps[0], "[data-step-label]")) == "Request"
        assert text(one(steps[-1], "[data-step-label]")) == "Response model"

    def test_the_canonical_example_shows_its_source(self, client: TestClient) -> None:
        example = one(_get(client), "#pattern-canonical")
        assert "async def" in text(example)
        assert ".py" in text(one(example, "[data-source-file]"))

    def test_every_rule_shows_why_and_how_many_follow(self, client: TestClient) -> None:
        rules = select(_get(client), "#pattern-rules [data-rule]")
        assert len(rules) == 5
        for rule in rules:
            assert text(one(rule, "[data-why]"))
            assert " of " in text(one(rule, "[data-followed]"))

    def test_instances_are_listed_by_tag(self, client: TestClient) -> None:
        groups = select(_get(client), "#pattern-instances [data-route-group]")
        assert "health" in [text(one(g, "h2")) for g in groups]


@pytest.mark.parametrize("key", list(overseer_patterns.PATTERNS))
def test_every_installed_pattern_renders_its_report(
    client: TestClient, key: str
) -> None:
    html = _get(client, "" if key == "route" else key)
    assert select(html, "#pattern-steps [data-step]")
    assert select(html, "#pattern-rules [data-rule]")
    assert select(html, "#pattern-instances [data-route-group]")


class TestMacroCatalog:
    @pytest.mark.parametrize("section", list(macro_catalog.FILES))
    def test_every_public_macro_has_an_example(self, section: str) -> None:
        examples = set(macro_catalog.EXAMPLES[section])
        assert examples == _public_macros(macro_catalog.FILES[section])

    @pytest.mark.parametrize("section", list(macro_catalog.FILES))
    def test_every_example_renders(self, section: str) -> None:
        for entry in macro_catalog.catalog(section):
            assert entry.error is None, (entry.name, entry.error)
            assert entry.signature.startswith(entry.name + "(")

    def test_a_broken_example_shows_its_error_instead_of_failing_the_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = macro_catalog.EXAMPLES["feedback"] | {
            "empty_state": "{{ empty_state( }}"
        }
        monkeypatch.setitem(macro_catalog.EXAMPLES, "feedback", broken)
        (entry,) = [
            e for e in macro_catalog.catalog("feedback") if e.name == "empty_state"
        ]
        assert entry.error and entry.preview is None

    def test_the_catalog_is_built_once_until_its_inputs_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = macro_catalog.catalog("layout")
        assert macro_catalog.catalog("layout") is first
        edited = macro_catalog.EXAMPLES["layout"] | {
            "copy_button": "{{ copy_button('x') }}"
        }
        monkeypatch.setitem(macro_catalog.EXAMPLES, "layout", edited)
        assert macro_catalog.catalog("layout") is not first

    def test_a_macro_shows_its_signature_notes_example_and_preview(
        self, client: TestClient
    ) -> None:
        entry = one(_get(client, "layout"), "#macro-badge")
        assert text(one(entry, "[data-signature]")) == "badge(label, tone=None)"
        assert "status word" in text(one(entry, "[data-doc]"))
        assert "badge(" in text(one(entry, "[data-example]"))
        assert select(entry, "[data-preview] [data-tone='ok']")

    def test_page_wide_macros_show_code_but_do_not_render(
        self, client: TestClient
    ) -> None:
        html = _get(client, "layout")
        assert not select(one(html, "#macro-dialog"), "[data-preview] dialog")
        assert len(select(html, "dialog#dialog")) <= 1
