"""Layout macros: card, stat_tile, chart_panel, dialog, badge, dropdown, confirm."""

import json

import pytest

from app.components.web_frontend.rendering import templates
from tests.web.dom import none, one, select, text

IMPORT = (
    '{% from "components/macros/layout.html" '
    "import card, stat_tile, chart_panel, dialog, badge, menu_item, dropdown, "
    "confirm, progress, page_header, figures, stats_strip, ranked_rows, "
    "tab_bar, tab_item, chip, facts, stat_row %}"
)


def render(source: str, **context: object) -> str:
    return templates.env.from_string(IMPORT + source).render(**context)


class TestCard:
    def test_is_a_titled_section(self) -> None:
        html = render('{% call card("Top payees") %}<p id="body">x</p>{% endcall %}')
        section = one(html, "section")
        heading = one(section, "h2")
        assert text(heading) == "Top payees"
        assert section.get("aria-labelledby") == heading.get("id")
        one(section, "#body")

    def test_optional_subtitle(self) -> None:
        html = render('{% call card("Spending", "last 90 days") %}x{% endcall %}')
        assert "last 90 days" in text(one(html, "section p"))


class TestStatTile:
    def test_is_a_definition_pair(self) -> None:
        html = render('{{ stat_tile("Assets", "$100.00") }}')
        assert text(one(html, "dt")) == "Assets"
        assert text(one(html, "dd")) == "$100.00"

    def test_it_lights_on_hover_only_when_a_click_does_something(self) -> None:
        """A teal border says "click me": a tile given attributes to act on
        carries the card hover, a plain figure does not."""
        plain = render('{{ stat_tile("Assets", "$1") }}')
        acting = render('{{ stat_tile("Assets", "$1", attrs=\'hx-get="/x"\') }}')
        assert "hover-card" not in (one(plain, "div").get("class") or "").split()
        assert "hover-card" in (one(acting, "div").get("class") or "").split()

    def test_negative_tone_marks_the_value(self) -> None:
        """Red once a figure goes negative; nothing for healthy figures,
        so the one number in trouble stands out."""
        bad = render('{{ stat_tile("Net worth", "-$5.00", negative=True) }}')
        good = render('{{ stat_tile("Net worth", "$5.00") }}')
        assert "text-error" in (one(bad, "dd").get("class") or "")
        assert "text-error" not in (one(good, "dd").get("class") or "")


class TestChartPanel:
    DATA = {"labels": ["Jan", "Feb"], "series": [{"label": "Net", "values": [1, 2]}]}

    def test_canvas_declares_its_kind_and_carries_json_data(self) -> None:
        html = render(
            '{{ chart_panel("nw", "Net worth", "line", data) }}', data=self.DATA
        )
        canvas = one(html, "canvas[data-chart]")
        assert canvas.get("data-chart") == "line"
        payload = one(html, 'script[type="application/json"]')
        assert payload.get("id") == canvas.get("data-chart-data")
        assert json.loads(payload.text or "") == self.DATA

    def test_is_a_titled_card(self) -> None:
        html = render(
            '{{ chart_panel("nw", "Net worth", "line", data) }}', data=self.DATA
        )
        assert text(one(html, "section h2")) == "Net worth"

    def test_drilldown_url_rides_the_canvas(self) -> None:
        html = render(
            '{{ chart_panel("sp", "Spending", "doughnut", data, drilldown="/overview/spending?days=90") }}',
            data=self.DATA,
        )
        assert one(html, "canvas").get("data-drilldown") == "/overview/spending?days=90"

    def test_no_executable_script(self) -> None:
        html = render(
            '{{ chart_panel("nw", "Net worth", "line", data) }}', data=self.DATA
        )
        none(html, 'script:not([type="application/json"])')


class TestDialog:
    def test_is_a_native_dialog_with_a_swap_target(self) -> None:
        html = render("{{ dialog() }}")
        dialog = one(html, "dialog#dialog")
        one(dialog, "#dialog-body")
        assert one(dialog, "button[aria-label='Close']") is not None

    def test_mounted_once_by_the_base_layout(self, shell: str) -> None:
        page = shell
        one(page, "dialog#dialog")
        one(page, "dialog#drawer")
        none(one(page, "main#app-content"), "dialog")
        assert len(select(page, "dialog")) == 2


class TestBadge:
    def test_tone_rides_a_data_attribute(self) -> None:
        html = render('{{ badge("Active", "ok") }}')
        badge = one(html, "[data-tone]")
        assert text(badge) == "Active" and badge.get("data-tone") == "ok"

    def test_no_tone_is_plain_text_without_a_dot(self) -> None:
        html = render('{{ badge("Jul 6") }}')
        none(html, "[data-tone] span")


class TestDropdown:
    def test_menu_items_are_the_menus_buttons(self) -> None:
        """What closes the menu (a click outside it, or on an item) is
        app.js's one listener, keyed on ``data-dropdown``
        (``tests/web/test_app_js.py``)."""
        html = render(
            '{% call dropdown("More") %}'
            '{{ menu_item("Edit", \'hx-get="/x/edit" hx-target="#dialog-body"\') }}'
            '{{ menu_item("Remove", \'hx-delete="/x"\', danger=True) }}'
            "{% endcall %}"
        )
        details = one(html, "details[data-dropdown]")
        items = select(details, "[role=menu] li button")
        assert [text(i) for i in items] == ["Edit", "Remove"]
        assert items[0].get("hx-get") == "/x/edit"
        assert "text-error" in items[1].get("class")

    def test_app_js_places_every_dropdown(self) -> None:
        """One listener in app.js places any dropdown on opening, keyed on
        ``data-dropdown`` (``tests/web/test_app_js.py``)."""
        html = render('{% call dropdown("More") %}<li>x</li>{% endcall %}')
        details = one(html, "details[data-dropdown]")
        one(details, "summary + [role=menu]")


class TestConfirm:
    def test_destructive_verb_and_a_way_out(self) -> None:
        html = render(
            '{{ confirm("Remove Savings?", "It goes away.", "/accounts/3") }}'
        )
        button = one(html, '[hx-delete="/accounts/3"]')
        assert button.get("hx-swap") == "none"
        assert "Savings" in text(one(html, "h2"))
        one(html, 'button[type="button"]:not([hx-delete])')

    def test_post_variant(self) -> None:
        html = render('{{ confirm("Run?", "", "/jobs", label="Run", method="post") }}')
        assert one(html, '[hx-post="/jobs"]') is not None


class TestStatTileExtras:
    def test_caption_and_attributes_make_a_clickable_cell(self) -> None:
        html = render(
            '{{ stat_tile("Bills", "$10.00", caption="3 bills", '
            'attrs=\'hx-get="/x/bills" hx-target="#dialog-body"\') }}'
        )
        tile = one(html, "div[hx-get]")
        assert tile.get("hx-target") == "#dialog-body"
        assert [text(dd) for dd in select(tile, "dd")] == ["$10.00", "3 bills"]


class TestProgress:
    def test_native_progress_clamped_to_the_unit_interval(self) -> None:
        assert one(render("{{ progress(0.25) }}"), "progress").get("value") == "0.25"
        assert (
            one(render('{{ progress(1.7, "error") }}'), "progress").get("value") == "1"
        )


class TestPageHeader:
    def test_title_subtitle_and_the_right_hand_side(self) -> None:
        html = render(
            '{% call page_header("Budget", "the month") %}<span id="r">x</span>{% endcall %}'
        )
        header = one(html, "header")
        assert text(one(header, "h1")) == "Budget" and "the month" in text(header)
        one(header, "#r")

    def test_figures_are_a_definition_list_the_stat_helper_reads(self) -> None:
        html = render(
            '{{ figures([{"label": "Assets", "value": "$1.00", "negative": False}, {"label": "Owed", "value": "-$2.00", "negative": True}]) }}'
        )
        assert text(select(html, "dl dt")[0]) == "Assets"
        assert "text-error" in select(html, "dd")[1].get("class")


class TestStatsStrip:
    def test_one_strip_with_a_cell_per_term(self) -> None:
        cells = [
            {
                "label": "Income",
                "value": "$10.00",
                "caption": "2 sources",
                "tone": None,
                "attrs": 'hx-get="/x/income"',
            },
            {
                "label": "This month",
                "value": "-$1.00",
                "caption": "short",
                "tone": "error",
                "attrs": "",
            },
        ]
        html = render("{{ stats_strip(cells, id='s') }}", cells=cells)
        strip = one(html, "dl#s")
        assert len(select(strip, "dt")) == 2
        assert one(strip, "[hx-get]").get("hx-get") == "/x/income"
        assert select(strip, "dd")[2].get("data-tone") == "error"


@pytest.mark.parametrize(
    "source",
    [
        '{{ badge("Down", "error") }}',
        '{{ progress(0.5, "error") }}',
        "{{ stats_strip([{'label': 'Owed', 'value': '1', 'tone': 'error'}]) }}",
    ],
)
def test_a_tone_is_coloured_in_one_place(source: str) -> None:
    """Every tone maps to its colour in input.css's ``.toned`` family, so an
    error is the same red on a badge, a bar and a stat."""
    toned = one(render(source), ".toned")
    assert toned.get("data-tone") == "error"
    colours = ("text-aegis-", "text-error")
    assert not [c for c in toned.get("class").split() if c.startswith(colours)]


class TestRankedRows:
    def test_bar_scales_to_the_ratio(self) -> None:
        rows = [
            {
                "label": "Market",
                "count": "2x",
                "value": "$45.00",
                "ratio": 1.0,
                "tone": "teal",
            },
            {
                "label": "Gas",
                "count": "1x",
                "value": "$20.00",
                "ratio": 0.444,
                "tone": "teal",
            },
        ]
        html = render("{{ ranked_rows(rows) }}", rows=rows)
        items = select(html, ".ranked li")
        assert len(items) == 2 and "Market" in text(items[0])
        assert one(items[1], "[style]").get("style") == "width: 44%"


class TestTabsAndChips:
    def test_tabs_are_an_underlined_tablist(self) -> None:
        html = render(
            '{% call tab_bar("Views", id="v") %}'
            '{{ tab_item("One", True, "/one") }}{{ tab_item("Two", False, "/two") }}'
            "{% endcall %}"
        )
        nav = one(html, "nav#v[role=tablist]")
        assert "border-b" in nav.get("class")
        links = select(nav, "a")
        assert [link.get("class") for link in links] == ["tab", "tab"]
        assert links[0].get("aria-current") == "page"  # .tab underlines it
        assert links[1].get("aria-current") is None

    def test_chip_is_the_date_range_recipe(self) -> None:
        active = one(render('{{ chip("30d", True, "/x?days=30") }}'), "a")
        idle = one(render('{{ chip("90d", False, "/x?days=90") }}'), "a")
        assert (
            "bg-aegis-teal/10" in active.get("class")
            and active.get("aria-current") == "page"
        )
        assert "bg-aegis-teal/10" not in idle.get("class")
        assert idle.get("class").startswith("text-xs px-2 py-0.5")


class TestFacts:
    def test_label_value_pairs_skip_blank_values(self) -> None:
        html = render(
            '{{ facts([("State", "Healthy"), ("Note", none), ("Tags", ["a", "b"])]) }}'
        )
        assert [text(dt) for dt in select(html, "dt")] == ["State", "Tags"]
        assert [text(dd) for dd in select(html, "dd")] == ["Healthy", "a, b"]


class TestStatRow:
    def test_label_over_value_figures(self) -> None:
        html = render('{{ stat_row([("p95 ms", "4.2"), ("Clients", 3)]) }}')
        assert [text(dt) for dt in select(html, "dt")] == ["p95 ms", "Clients"]
        assert [text(dd) for dd in select(html, "dd")] == ["4.2", "3"]


def test_a_toggle_action_shows_when_it_is_on() -> None:
    """Wrap, Pause: a pressed action reads as on, as a pressed chip does."""
    html = render(
        '{% from "components/macros/form.html" import action %}{{ action("Wrap", \'aria-pressed="true"\') }}'
    )
    assert "action" in one(html, "button").get("class").split()  # input.css


def test_a_primary_button_is_as_tall_as_an_action() -> None:
    """Save stands as tall as Read pages: one button height, whichever
    macro drew it."""
    html = render(
        '{% from "components/macros/form.html" import action, primary_button %}'
        '{{ primary_button("Save") }}{{ action("Read pages", "", "primary") }}'
    )
    save, read = select(html, "button")

    def size(button: object) -> set[str]:
        classes = (button.get("class") or "").split()  # type: ignore[attr-defined]
        return {c for c in classes if c.startswith(("text-xs", "text-sm", "py-", "px-"))}

    assert size(save) == size(read)
