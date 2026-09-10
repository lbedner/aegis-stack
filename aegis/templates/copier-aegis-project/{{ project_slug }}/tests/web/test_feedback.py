"""Pattern 6, feedback: toasts, empty states, error banners.

Toasts are driven by the ``HX-Trigger`` response header. A route says
``with_toast(response, "Saved")``; htmx raises a ``toast`` DOM event; the
region in the base layout shows it. No reload, no storage.
"""

import json

from fastapi.testclient import TestClient
import pytest
from starlette.responses import Response

from app.components.web_frontend.rendering import (
    close_dialog,
    dialog_done,
    hx_dialog,
    hx_dialog_post,
    navigate,
    templates,
    with_toast,
)
from tests.web.dom import none, one, select, text, triggers


class TestWithToast:
    def test_sets_the_trigger_header(self) -> None:
        response = with_toast(Response(), "Saved")
        assert json.loads(response.headers["HX-Trigger"]) == {
            "toast": {"text": "Saved", "tone": "ok"}
        }

    def test_error_tone(self) -> None:
        response = with_toast(Response(), "Nope", tone="error")
        assert json.loads(response.headers["HX-Trigger"])["toast"]["tone"] == "error"

    def test_merges_with_an_existing_trigger(self) -> None:
        """A route may already be triggering another event; both must
        survive in the one header htmx reads."""
        response = Response()
        response.headers["HX-Trigger"] = json.dumps({"count-changed": {"n": 3}})
        with_toast(response, "Saved")
        triggers = json.loads(response.headers["HX-Trigger"])
        assert triggers["count-changed"] == {"n": 3}
        assert triggers["toast"]["text"] == "Saved"


class TestToastRegion:
    @pytest.fixture
    def page(self, client: TestClient) -> str:
        return client.get("/").text

    def test_present_outside_the_content_area(self, page: str) -> None:
        """Lives in the base layout, not the swap target, so it survives
        section navigation and stays fixed to the viewport."""
        one(page, "#toasts")
        none(one(page, "main#app-content"), "#toasts")

    def test_is_a_polite_live_region(self, page: str) -> None:
        assert one(page, "#toasts").get("aria-live") == "polite"

    def test_listens_for_the_toast_event(self, page: str) -> None:
        assert one(page, "#toasts").get("@toast.window") is not None

    def test_reload_snackbar_is_gone(self, page: str) -> None:
        for banned in ("appFlashSnackbar", "__app_snackbar", 'x-data="snackbar()"'):
            assert banned not in page, banned


def render(source: str, **context: object) -> str:
    return templates.env.from_string(
        '{% from "components/macros/feedback.html" import empty_state, error_banner %}'
        + source
    ).render(**context)


class TestEmptyState:
    def test_names_what_is_missing_and_what_to_do(self) -> None:
        html = render('{{ empty_state("No accounts yet", "Add one to begin.") }}')
        assert text(one(html, "h2")) == "No accounts yet"
        assert "Add one to begin." in text(one(html, "div"))

    def test_hint_is_optional(self) -> None:
        html = render('{{ empty_state("Nothing here") }}')
        assert text(one(html, "h2")) == "Nothing here"
        none(html, "p")


class TestErrorBanner:
    def test_renders_nothing_without_errors(self) -> None:
        assert render("{{ error_banner([]) }}").strip() == ""
        assert render("{{ error_banner(none) }}").strip() == ""

    def test_lists_every_error_as_an_alert(self) -> None:
        html = render(
            '{{ error_banner(["Amount is required", "Date is in the future"]) }}'
        )
        banner = one(html, '[role="alert"]')
        assert [text(li) for li in select(banner, "li")] == [
            "Amount is required",
            "Date is in the future",
        ]


class TestCloseDialog:
    def test_fires_after_settle_not_before_the_swap(self) -> None:
        """A plain HX-Trigger would close the dialog and then the swap into
        #dialog-body would re-open it, empty."""
        response = close_dialog(Response())
        assert "HX-Trigger" not in response.headers
        assert json.loads(response.headers["HX-Trigger-After-Settle"]) == {
            "dialog:close": None
        }

    def test_stacks_with_a_toast(self) -> None:
        response = close_dialog(with_toast(Response(), "Saved"))
        fired = triggers(response)
        assert "dialog:close" in fired and fired["toast"]["text"] == "Saved"


class TestNavigate:
    def test_sets_hx_location_for_the_content_area(self) -> None:
        response = navigate(Response(), "/accounts/3")
        assert json.loads(response.headers["HX-Location"]) == {
            "path": "/accounts/3",
            "target": "#app-content",
        }

    def test_closes_the_dialog_before_htmx_follows_the_location(self) -> None:
        """HX-Location is followed instead of swapped, so an after-settle
        close would never fire; the plain trigger is processed first."""
        response = navigate(Response(), "/accounts/3")
        assert json.loads(response.headers["HX-Trigger"]) == {"dialog:close": None}


class TestOobMacro:
    def test_marks_a_sibling_out_of_band(self) -> None:
        html = render(
            '{% from "components/macros/feedback.html" import oob %}'
            '{% call oob("count", tag="p") %}3 left{% endcall %}'
        )
        element = one(html, "p#count")
        assert element.get("hx-swap-oob") == "true" and text(element) == "3 left"


class TestDialogHelpers:
    """One definition of how the modal is opened, posted to, and finished."""

    def test_open_and_post_attributes_name_the_one_body(self) -> None:
        opener = one(f"<button {hx_dialog('/accounts/new')}></button>", "button")
        assert opener.get("hx-get") == "/accounts/new"
        assert opener.get("hx-target") == "#dialog-body"

        form = one(f"<form {hx_dialog_post('/accounts/new')}></form>", "form")
        assert form.get("hx-post") == "/accounts/new"
        assert form.get("hx-target") == "#dialog-body"

    def test_an_opener_can_carry_more(self) -> None:
        html = (
            f"""<button {hx_dialog("/x", 'hx-include="[name=k]:checked"')}></button>"""
        )
        assert one(html, "button").get("hx-include") == "[name=k]:checked"

    def test_done_closes_says_and_navigates(self) -> None:
        response = dialog_done("/accounts/3", "Added Ally.")
        assert json.loads(response.headers["HX-Location"])["path"] == "/accounts/3"
        fired = json.loads(response.headers["HX-Trigger"])
        assert "dialog:close" in fired and fired["toast"]["text"] == "Added Ally."


class TestRangeChips:
    def test_one_exclusive_radio_row(self) -> None:
        html = render(
            '{% from "components/macros/form.html" import range_chips %}'
            "{{ range_chips(((7, '7d'), (30, '1m'), (9999, 'All')), 30) }}"
        )
        chips = select(html, "fieldset label")
        assert [text(c) for c in chips] == ["7d", "1m", "All"]
        radios = select(html, 'input[type="radio"]')
        assert {r.get("name") for r in radios} == {"days"}
        assert [r.get("value") for r in radios if r.get("checked") is not None] == [
            "30"
        ]
        assert "sr-only" in radios[0].get("class")  # the pill is the label
