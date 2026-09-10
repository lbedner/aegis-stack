"""The web test kit itself: the ``hx`` client and the DOM helpers.

Every page test in this package leans on these, so they get their own
tests. A helper that silently matched nothing would make every downstream
assertion pass vacuously.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from tests.web.dom import location, none, one, oob, select, table_rows, text, triggers

PAGE = """<!DOCTYPE html><html><head><title>t</title></head><body>
<main id="app-content">
  <table class="tbl"><tr><td class="c">a</td><td class="c">b</td></tr></table>
  <p class="msg">  hello <b>world</b> </p>
</main></body></html>"""

FRAGMENT = '<div id="row-1"><span class="amt">12.00</span></div>'


class TestSelect:
    def test_returns_every_match(self) -> None:
        assert len(select(PAGE, "td.c")) == 2

    def test_returns_empty_list_on_no_match(self) -> None:
        assert select(PAGE, "nav") == []

    def test_works_on_a_bare_fragment(self) -> None:
        """Fragments have no <html>; the parser must not choke or wrap
        them in a way that breaks selectors."""
        assert len(select(FRAGMENT, "#row-1 .amt")) == 1

    def test_fragment_wrapper_is_never_a_match(self) -> None:
        """The kit wraps fragments in a div to parse them; that div must
        not answer for ``div`` or every empty-state test passes twice."""
        assert len(select('<div id="only"></div>', "div")) == 1
        assert select("<p>x</p>", "div") == []

    def test_full_document_keeps_its_head(self) -> None:
        """``head script`` must resolve on a real page, so a document is
        parsed as a document rather than wrapped."""
        assert len(select(PAGE, "head title")) == 1


class TestOne:
    def test_returns_the_single_match(self) -> None:
        assert one(PAGE, "table").get("class") == "tbl"

    def test_fails_loudly_on_zero_matches(self) -> None:
        with pytest.raises(AssertionError, match="expected 1 .* got 0"):
            one(PAGE, "nav")

    def test_fails_loudly_on_many_matches(self) -> None:
        with pytest.raises(AssertionError, match="expected 1 .* got 2"):
            one(PAGE, "td.c")


class TestText:
    def test_collapses_whitespace_and_descends(self) -> None:
        assert text(one(PAGE, "p.msg")) == "hello world"


class TestNone:
    def test_passes_when_nothing_matches(self) -> None:
        none(PAGE, "nav")

    def test_fails_naming_what_was_found(self) -> None:
        """Absence is a real assertion: the delete button must not render
        on a read-only view, the empty state must replace the table."""
        with pytest.raises(AssertionError, match="expected no 'td.c', found 2"):
            none(PAGE, "td.c")


@pytest.fixture
def app() -> FastAPI:
    """Override the real app with one route that echoes the htmx header."""
    tiny = FastAPI()

    @tiny.get("/echo")
    def echo(request: Request) -> dict[str, str | None]:
        return {"hx": request.headers.get("HX-Request")}

    return tiny


class TestHxReplace:
    def test_emits_the_self_replacing_recipe(self) -> None:
        from app.components.web_frontend.rendering import hx_replace

        attrs = one(f"<a {hx_replace('/items?page=2', '#items')}>n</a>", "a")
        assert attrs.get("hx-get") == "/items?page=2"
        assert attrs.get("hx-target") == attrs.get("hx-select") == "#items"
        assert attrs.get("hx-swap") == "outerHTML"
        assert attrs.get("hx-push-url") == "true"
        assert attrs.get("hx-select-oob") is None

    def test_oob_and_escaping(self) -> None:
        from app.components.web_frontend.rendering import hx_replace

        html = f"<a {hx_replace('/a?x=1&y=2', '#d', oob='#list')}>n</a>"
        a = one(html, "a")
        assert a.get("hx-select-oob") == "#list"
        assert a.get("hx-get") == "/a?x=1&y=2"
        assert "&amp;" in str(hx_replace("/a?x=1&y=2", "#d"))


class TestHxClient:
    def test_hx_client_sends_the_htmx_request_header(self, hx: TestClient) -> None:
        assert hx.get("/echo").json() == {"hx": "true"}

    def test_plain_client_does_not(self, client: TestClient) -> None:
        assert client.get("/echo").json() == {"hx": None}


class TestOob:
    def test_splits_primary_content_from_out_of_band_siblings(self) -> None:
        primary, siblings = oob(
            '<tr id="a"><td>x</td></tr><span id="n" hx-swap-oob="true">1</span>'
        )
        assert [el.get("id") for el in primary] == ["a"]
        assert [el.get("id") for el in siblings] == ["n"]

    def test_empty_primary_when_only_siblings(self) -> None:
        primary, siblings = oob('<tr id="a" hx-swap-oob="outerHTML"><td>x</td></tr>')
        assert primary == [] and len(siblings) == 1


class TestTableRows:
    def test_cells_by_header_label(self) -> None:
        rows = table_rows(
            "<table><thead><tr><th>Name</th><th>Amount</th></tr></thead>"
            "<tbody><tr><td>Rent</td><td>$1</td></tr></tbody></table>"
        )
        assert text(rows[0]["Name"]) == "Rent" and text(rows[0]["Amount"]) == "$1"


class TestTriggers:
    def test_merges_the_three_trigger_headers(self) -> None:
        class Response:
            headers = {
                "HX-Trigger": '{"toast": {"text": "ok"}}',
                "HX-Trigger-After-Settle": '{"dialog:close": null}',
            }

        assert triggers(Response()) == {"toast": {"text": "ok"}, "dialog:close": None}


class TestLocation:
    def test_reads_where_a_navigating_response_sends_the_page(self) -> None:
        class Response:
            headers = {"HX-Location": '{"path": "/accounts/3", "target": "#app-content"}'}

        assert location(Response()) == "/accounts/3"

