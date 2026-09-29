"""``data_table``: the one table macro in the app.

Columns are declared, rows are objects or dicts, and formatting goes
through the filters, so a page never hand-writes a ``<table>``.
"""

from dataclasses import dataclass
from datetime import date

from app.components.web_frontend.rendering import templates
from tests.web.dom import none, one, select, text

COLUMNS = [
    {"key": "when", "label": "Date", "kind": "date"},
    {"key": "name", "label": "Name"},
    {"key": "amount", "label": "Amount", "kind": "money", "align": "right"},
]


@dataclass
class Row:
    when: date
    name: str
    amount: int
    currency: str = "USD"


def render(columns: list[dict], rows: list, **kwargs: object) -> str:
    template = templates.env.from_string(
        '{% from "components/macros/table.html" import data_table %}'
        "{{ data_table(columns, rows, **kwargs) }}"
    )
    return template.render(columns=columns, rows=rows, kwargs=kwargs)


class TestDataTable:
    def test_a_column_may_render_its_own_header(self) -> None:
        template = templates.env.from_string(
            '{% from "components/macros/table.html" import data_table %}'
            '{% macro box() %}<input type="checkbox" data-all>{% endmacro %}'
            '{{ data_table([{"key": "name", "label": "Name", "header": box}], rows) }}'
        )
        html = template.render(rows=[{"name": "Coffee"}])
        assert select(html, "thead th input[data-all]")

    def test_headers_come_from_the_column_labels(self) -> None:
        html = render(COLUMNS, [Row(date(2026, 7, 15), "Coffee", -450)])
        assert [text(th) for th in select(html, "thead th")] == [
            "Date",
            "Name",
            "Amount",
        ]

    def test_cells_are_formatted_by_kind(self) -> None:
        html = render(COLUMNS, [Row(date(2026, 7, 15), "Coffee", -450)])
        cells = [text(td) for td in select(html, "tbody td")]
        assert cells[0].startswith("Jul 15")
        assert cells[1] == "Coffee"
        assert cells[2] == "-$4.50"

    def test_money_honours_the_row_currency(self) -> None:
        html = render(COLUMNS, [Row(date(2026, 7, 15), "Tea", 250, currency="GBP")])
        assert text(select(html, "tbody td")[2]) == "£2.50"

    def test_right_aligned_columns_align_header_and_cells(self) -> None:
        html = render(COLUMNS, [Row(date(2026, 7, 15), "Coffee", -450)])
        assert "text-right" in (select(html, "thead th")[2].get("class") or "")
        assert "text-right" in (select(html, "tbody td")[2].get("class") or "")

    def test_accepts_dict_rows(self) -> None:
        html = render(
            [{"key": "name", "label": "Name"}], [{"name": "Rent"}, {"name": "Gas"}]
        )
        assert [text(td) for td in select(html, "tbody td")] == ["Rent", "Gas"]

    def test_empty_rows_render_the_empty_state_instead_of_a_table(self) -> None:
        html = render(COLUMNS, [], empty="No transactions yet")
        none(html, "table")
        assert text(one(html, "h2")) == "No transactions yet"

    def test_empty_has_a_default_title(self) -> None:
        html = render(COLUMNS, [])
        assert text(one(html, "h2")) == "Nothing here yet"

    def test_blank_values_render_as_a_dash(self) -> None:
        html = render([{"key": "name", "label": "Name"}], [{"name": None}])
        assert text(one(html, "tbody td")) == "-"


class TestRowsAndActions:
    def test_row_id_names_each_row(self) -> None:
        html = render(COLUMNS, [{"id": 1, "name": "a", "amount": 100}], row_id="txn")
        one(html, "tr#txn-1")

    def test_a_call_block_adds_an_actions_column(self) -> None:
        template = templates.env.from_string(
            '{% from "components/macros/table.html" import data_table %}'
            '{% call(row) data_table(columns, rows, row_id="r") %}'
            '<button data-for="{{ row.id }}">x</button>{% endcall %}'
        )
        html = template.render(
            columns=COLUMNS, rows=[{"id": 7, "name": "a", "amount": 1}]
        )
        assert len(select(html, "thead th")) == len(COLUMNS) + 1
        assert one(html, "tr#r-7 td:last-child button").get("data-for") == "7"

    def test_table_row_can_answer_out_of_band(self) -> None:
        template = templates.env.from_string(
            '{% from "components/macros/table.html" import table_row %}'
            '{{ table_row(columns, row, id="r-1", oob=True) }}'
        )
        html = template.render(columns=COLUMNS, row={"id": 1, "name": "a", "amount": 1})
        assert one(html, "tr#r-1").get("hx-swap-oob") == "outerHTML"


class TestCellKinds:
    def test_status_renders_a_badge(self) -> None:
        columns = [{"key": "state", "label": "State", "kind": "status"}]
        html = render(columns, [{"state": {"label": "Overdue", "tone": "warn"}}])
        badge = one(html, "td [data-tone]")
        assert text(badge) == "Overdue" and badge.get("data-tone") == "warn"

    def test_signed_money_carries_a_plus_and_a_tone(self) -> None:
        columns = [
            {"key": "amount", "label": "Amount", "kind": "money", "signed": True}
        ]
        html = render(columns, [{"amount": 250}, {"amount": -250}])
        cells = select(html, "tbody td")
        assert text(cells[0]) == "+$2.50" and "text-aegis-teal" in cells[0].get("class")
        assert text(cells[1]) == "-$2.50" and "text-error" in cells[1].get("class")

    def test_code_is_monospace(self) -> None:
        columns = [{"key": "key", "label": "Key", "kind": "code"}]
        assert text(one(render(columns, [{"key": "cache:user:1"}]), "td code")) == (
            "cache:user:1"
        )

    def test_a_link_opens_its_item_in_the_target(self) -> None:
        columns = [
            {"key": "title", "label": "Title", "kind": "link", "target": "#main"}
        ]
        link = one(
            render(columns, [{"title": {"label": "Lease", "url": "/d?id=1"}}]), "td a"
        )
        assert text(link) == "Lease" and link.get("href") == "/d?id=1"
        assert link.get("hx-target") == "#main"

    def test_a_wrapping_column_wraps(self) -> None:
        columns = [{"key": "rule", "label": "Rule", "wrap": True}]
        cell = one(render(columns, [{"rule": "Host(`a`) && Path(`/b`)"}]), "tbody td")
        assert "whitespace-normal" in cell.get("class")

    def test_an_avatar_shows_the_brand_mark_before_the_name(self) -> None:
        columns = [{"key": "name", "label": "Provider", "kind": "avatar"}]
        html = render(columns, [{"name": "Anthropic", "icon_url": "/icons/anthropic"}])
        assert one(html, "td img").get("src") == "/icons/anthropic"
        assert text(one(html, "td")) == "Anthropic"

    def test_without_a_mark_the_avatar_is_the_initial(self) -> None:
        columns = [{"key": "name", "label": "Provider", "kind": "avatar"}]
        html = render(columns, [{"name": "groq", "icon_url": None}])
        assert one(html, "td [data-avatar]").get("data-avatar") == "G"
        assert not select(html, "td img")

    def test_toned_money_colours_without_the_plus(self) -> None:
        columns = [
            {"key": "balance", "label": "Balance", "kind": "money", "toned": True}
        ]
        html = render(columns, [{"balance": -100}])
        cell = one(html, "tbody td")
        assert text(cell) == "-$1.00" and "text-error" in cell.get("class")


class TestDetailRows:
    SOURCE = (
        '{% from "components/macros/table.html" import data_table %}'
        '{% macro more(row) %}<p class="more">{{ row.name }} detail</p>{% endmacro %}'
        "{{ data_table(columns, rows, detail=more) }}"
    )

    def _render(self) -> str:
        rows = [
            Row(date(2026, 7, 15), "Coffee", -450),
            Row(date(2026, 7, 16), "Tea", -300),
        ]
        return templates.env.from_string(self.SOURCE).render(columns=COLUMNS, rows=rows)

    def test_each_row_carries_a_hidden_detail_row(self) -> None:
        html = self._render()
        details = select(html, "tr[data-detail]")
        assert [text(one(d, ".more")) for d in details] == [
            "Coffee detail",
            "Tea detail",
        ]
        assert all(d.get("x-show") == "open" for d in details)
        assert one(details[0], "td").get("colspan") == str(len(COLUMNS) + 1)

    def test_a_button_toggles_the_detail(self) -> None:
        html = self._render()
        buttons = select(html, "tbody button[aria-expanded]")
        assert len(buttons) == 2
        assert buttons[0].get("aria-expanded") == "false"

    def test_without_detail_there_is_no_toggle(self) -> None:
        html = render(COLUMNS, [Row(date(2026, 7, 15), "Coffee", -450)])
        none(html, "tr[data-detail]")
        none(html, "button[aria-expanded]")


class TestRenderedCells:
    def test_a_column_macro_renders_the_cell(self) -> None:
        source = (
            '{% from "components/macros/table.html" import data_table %}'
            '{% macro shout(value) %}<b class="shout">{{ value|upper }}</b>{% endmacro %}'
            '{{ data_table([{"key": "name", "label": "Name", "render": shout}], rows) }}'
        )
        html = templates.env.from_string(source).render(rows=[{"name": "tea"}])
        assert text(one(html, "td b.shout")) == "TEA"


class TestActionsArgument:
    """Actions can be passed as a macro, so one table serves viewers with and
    without them instead of being written twice."""

    SOURCE = (
        '{% from "components/macros/table.html" import data_table %}'
        '{% macro verbs(row) %}<button class="verb">{{ row.name }}</button>{% endmacro %}'
        "{{ data_table(columns, rows, actions=verbs if show else none) }}"
    )

    def _render(self, show: bool) -> str:
        rows = [Row(date(2026, 7, 15), "Coffee", -450)]
        return templates.env.from_string(self.SOURCE).render(
            columns=COLUMNS, rows=rows, show=show
        )

    def test_a_macro_adds_the_actions_column(self) -> None:
        assert text(one(self._render(True), "td button.verb")) == "Coffee"

    def test_none_leaves_it_out(self) -> None:
        html = self._render(False)
        none(html, "button.verb")
        assert len(select(html, "thead th")) == len(COLUMNS)
