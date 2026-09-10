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

    def test_toned_money_colours_without_the_plus(self) -> None:
        columns = [
            {"key": "balance", "label": "Balance", "kind": "money", "toned": True}
        ]
        html = render(columns, [{"balance": -100}])
        cell = one(html, "tbody td")
        assert text(cell) == "-$1.00" and "text-error" in cell.get("class")
