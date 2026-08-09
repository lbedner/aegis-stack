"""The Projected tab: chart beside the ledger, not above it.

Stacked, the chart ate the height and left the ledger ~4 visible rows -
"I need to be able to see more transactions." The two halves answer one
question together (the line says WHEN the balance turns, the rows say
WHAT turns it), so they sit side by side rather than in sub-tabs, which
would hide exactly that correlation.
"""

import flet as ft

from app.components.frontend.controls import DataTable

from app.components.frontend.dashboard.modals.finance_recurring_tab import (
    projection_columns,
    projection_layout,
)


class TestTheColumns:
    def test_the_column_set(self) -> None:
        headers = [c.header for c in projection_columns()]
        assert headers == ["Date", "Name", "Category", "Account", "Amount", "Balance"]

    def test_name_is_the_identity_column(self) -> None:
        by_header = {c.header: c for c in projection_columns()}
        assert by_header["Name"].hideable is False

    def test_category_and_account_ship_hidden(self) -> None:
        """Both are one click away in the picker; neither may cost the
        NAME column its width. Confirmed live at a 1459px window: the
        ledger's ~565px share could not seat the fixed columns, so the
        one flex column - Name, the identity column - collapsed to zero
        and the ledger showed category strings where bill names belong
        ("I need the bill name though")."""
        by_header = {c.header: c for c in projection_columns()}
        for header in ("Category", "Account"):
            assert by_header[header].visible is False
            assert by_header[header].hideable is True

    def test_the_default_view_is_date_name_amount_balance(self) -> None:
        assert [
            c.header for c in projection_columns() if c.visible
        ] == ["Date", "Name", "Amount", "Balance"]

    def test_the_flex_column_survives_the_narrow_split(self) -> None:
        """The width budget, pinned. The ledger gets 9/20 of the modal;
        at a small-laptop window that is ~550px. The default-visible
        FIXED widths plus the picker gutter and cell spacing must leave
        the flex Name column real room inside that, or it silently
        renders at zero width - which no control-tree test can see, and
        which is exactly what shipped."""
        fixed = sum(
            c.width or 0 for c in projection_columns() if c.visible and c.width
        )
        picker, spacing_budget, min_name = 28, 5 * 16, 110
        assert fixed + picker + spacing_budget + min_name <= 550, (
            f"visible fixed widths total {fixed}px - the Name column "
            "collapses on a narrow window"
        )


class TestTheLayout:
    def _built(self) -> tuple[ft.Row, ft.Control, ft.Control]:
        chart = ft.Container()
        table = ft.Container()
        return projection_layout(chart, table), chart, table

    def test_chart_and_ledger_are_side_by_side(self) -> None:
        row, chart, table = self._built()
        assert isinstance(row, ft.Row)
        assert row.controls[0].content is chart
        assert row.controls[1].content is table

    def test_the_ledger_gets_comparable_width(self) -> None:
        """The point of the change: the table was starving. Both sides
        hold real weight - neither is a sliver of the other."""
        row, _chart, _table = self._built()
        chart_flex, table_flex = (c.expand for c in row.controls)
        assert chart_flex >= table_flex  # the line needs room to read
        assert table_flex / chart_flex >= 0.6

    def test_the_row_is_bounded(self) -> None:
        """STRETCH against an unbounded parent renders NOTHING in Flet's
        release build (the import-review dialog shipped that bug). This
        row stretches its children, so it must carry its own bound."""
        row, _chart, _table = self._built()
        assert row.vertical_alignment == ft.CrossAxisAlignment.STRETCH
        assert row.expand is True


class TestTheLedgerRenders:
    """Through the real DataTable, because the column list being right
    does not mean the rendered header is: shipping Account hidden made
    the NAME column vanish from the live table too, which is the one
    column the ledger cannot lose ("I need the bill name though")."""

    def _table(self) -> DataTable:
        return DataTable(
            columns=projection_columns(),
            rows=[
                [
                    "Aug 9, 2026",
                    "Paramount+",
                    "Bills & Utilities:Streaming",
                    "AMEX",
                    "-$8.99",
                    "-$268.03",
                ]
            ],
            column_picker=True,
        )

    @staticmethod
    def _texts(node: ft.Control) -> list[str]:
        out: list[str] = []

        def walk(n: object) -> None:
            value = getattr(n, "value", None)
            if isinstance(value, str) and value:
                out.append(value)
            content = getattr(n, "content", None)
            if content is not None:
                walk(content)
            for child in getattr(n, "controls", None) or []:
                walk(child)

        walk(node)
        return out

    def test_the_header_shows_every_visible_column(self) -> None:
        rendered = self._texts(self._table())
        for header in ("Date", "Name", "Amount", "Balance"):
            assert header in rendered, f"{header} missing from the rendered table"
        assert "Account" not in rendered
        assert "Category" not in rendered

    def test_the_bill_name_reaches_the_row(self) -> None:
        rendered = self._texts(self._table())
        assert "Paramount+" in rendered
        # Hidden columns' cells stay hidden with them.
        assert "AMEX" not in rendered
        assert "Streaming" not in rendered
