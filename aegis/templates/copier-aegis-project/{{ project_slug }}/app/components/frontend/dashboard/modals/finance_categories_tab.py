"""The Categories tab: the taxonomy transactions are grouped by.

Categories arrive with an import - a Quicken category path like
``Bills & Utilities:Streaming`` becomes a two-segment category name - so
this surface is a READ of what the source already organized, not a place
to invent a scheme from scratch.

The hierarchy lives in the name itself: ``finance_category.parent_id`` is
a provider field nothing populates, so the top-level group is the text
before the first ``:``. That is exactly how the names were built on
import, which makes it a faithful regrouping rather than a guess.
"""

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    H3Text,
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.data_table import DataTable, DataTableColumn
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    headline_stat,
    ledger_amount_color,
)
from app.components.frontend.theme import AegisTheme as Theme

_CATEGORIES_URL = "/api/v1/finance/categories"
_UNGROUPED = "Ungrouped"

# ONE column grid for both levels. A nested table gave the children a
# second header, a second border, and columns that did not line up with
# the parent's - which is what made the page read as two tables stacked
# rather than one tree. Sorting is off: a header sort would reorder rows
# independently of their parents and tear the hierarchy apart.
_COLUMNS = [
    DataTableColumn("Category", style="body", sortable=False),
    DataTableColumn("Kind", width=100, style="secondary", sortable=False),
    DataTableColumn(
        "Transactions", width=120, alignment="right", style="secondary", sortable=False
    ),
    DataTableColumn("Net", width=140, alignment="right", sortable=False),
    DataTableColumn("Last used", width=110, style="secondary", sortable=False),
]

# Indent for a child row, so the tree's depth reads without a rule line.
_CHILD_INDENT = 26


def _split(name: str) -> tuple[str, str]:
    """``"Food & Dining:Groceries"`` -> ``("Food & Dining", "Groceries")``.

    A single-segment name is its own group with an empty leaf, so a flat
    category (``Shopping``) still gets a row instead of vanishing.
    """
    head, sep, tail = name.partition(":")
    if not sep:
        return head.strip() or _UNGROUPED, ""
    return head.strip() or _UNGROUPED, tail.strip()


class CategoriesTab(ft.Container):
    """Categories grouped by their top-level segment, with usage."""

    _RANGES = [
        ("1m", 30),
        ("3m", 90),
        ("6m", 180),
        ("1y", 365),
        ("All", 9999),
    ]

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._days = 365
        self._body = ft.Container(expand=True)
        # Which groups are open, and the grouped data behind the rows.
        # Expansion survives a range change: re-picking a window should
        # not collapse everything you had opened.
        self._expanded: set[str] = set()
        self._groups: list[tuple[str, list[dict]]] = []
        self._stats = ft.Row(
            [],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                H3Text("Categories"),
                                SecondaryText(
                                    "How your transactions are grouped, "
                                    "as your source app classified them"
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Container(expand=True),
                        DateRangeChips(
                            options=self._RANGES,
                            selected_days=self._days,
                            on_change=self._on_range,
                        ),
                        self._stats,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.LG,
                ),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    def _on_range(self, days: int) -> None:
        self._days = days
        if self.page:
            self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        # 9999 is the chips' "All" sentinel: send no window at all rather
        # than a 27-year one.
        params = {} if self._days >= 9000 else {"days": self._days}
        data = await api.get(_CATEGORIES_URL, params=params)
        items = data.get("items", []) if isinstance(data, dict) else []

        groups: dict[str, list[dict]] = {}
        for item in items:
            head, leaf = _split(item.get("name") or "")
            item["_leaf"] = leaf or head
            groups.setdefault(head, []).append(item)

        used = [i for i in items if i.get("transaction_count")]
        self._stats.controls = [
            headline_stat("Groups", f"{len(groups):,}", Theme.Colors.TEXT_PRIMARY),
            headline_stat("Categories", f"{len(items):,}", Theme.Colors.TEXT_PRIMARY),
            headline_stat("Used in range", f"{len(used):,}", Theme.Colors.TEXT_PRIMARY),
        ]

        # Busiest group first: the taxonomy's shape is more useful than
        # its alphabet when you are looking for where the money goes.
        self._groups = sorted(
            groups.items(),
            key=lambda kv: sum(c.get("transaction_count", 0) for c in kv[1]),
            reverse=True,
        )
        self._render()
        if self._stats.page is not None:
            self._stats.update()

    def _render(self) -> None:
        """Flatten the tree into one table: every group, plus the children
        of the expanded ones. Rebuilt on each toggle - cheap, because the
        data is already in memory, and it keeps one source of truth for
        row order instead of a widget tree that can drift from it."""
        rows: list[list] = []
        meta: list[str | None] = []  # group name for a group row, else None
        for head, children in self._groups:
            expanded = head in self._expanded
            rows.append(self._group_cells(head, children, expanded))
            meta.append(head)
            if not expanded:
                continue
            for child in sorted(
                children,
                key=lambda c: (-c.get("transaction_count", 0), c.get("_leaf") or ""),
            ):
                rows.append(self._child_cells(child))
                meta.append(None)

        def _on_row_click(index: int) -> None:
            head = meta[index] if index < len(meta) else None
            if head is None:
                return  # a child row is not a disclosure target
            self._expanded.symmetric_difference_update({head})
            self._render()
            if self._body.page is not None:
                self._body.update()

        self._body.content = ft.Container(
            content=DataTable(
                columns=_COLUMNS,
                rows=rows,
                row_padding=6,
                show_header_border=True,
                show_row_borders=True,
                on_row_click=_on_row_click,
                # expand=True makes the body a virtualized ListView, which
                # is what gives the page its scroll - 54 groups fully
                # expanded is hundreds of rows.
                expand=True,
                empty_message=(
                    "No categories yet. They arrive with your first import."
                ),
            ),
            expand=True,
        )
        if self._body.page is not None:
            self._body.update()

    def _group_cells(self, head: str, children: list[dict], expanded: bool) -> list:
        count = sum(c.get("transaction_count", 0) for c in children)
        net = sum(c.get("total", 0) for c in children)
        plural = "ies" if len(children) != 1 else "y"
        return [
            ft.Row(
                [
                    ft.Icon(
                        ft.Icons.ARROW_DROP_DOWN if expanded else ft.Icons.ARROW_RIGHT,
                        size=18,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    TableNameText(head),
                    SecondaryText(
                        f"{len(children):,} categor{plural}",
                        size=Theme.Typography.BODY_SMALL,
                    ),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            SecondaryText(""),
            NumericText(f"{count:,}", color=Theme.Colors.TEXT_SECONDARY),
            NumericText(_usd(net), color=ledger_amount_color(net)),
            SecondaryText(""),
        ]

    def _child_cells(self, child: dict) -> list:
        # An unused category is dimmed rather than hidden: it is real
        # taxonomy the import carried over, and seeing it is how you know
        # there is something to prune.
        unused = not child.get("transaction_count")
        name_color = (
            Theme.Colors.TEXT_SECONDARY if unused else Theme.Colors.TEXT_PRIMARY
        )
        return [
            ft.Container(
                content=BodyText(child.get("_leaf") or "", color=name_color),
                padding=ft.padding.only(left=_CHILD_INDENT),
            ),
            SecondaryText(child.get("classification") or ""),
            NumericText(
                f"{child.get('transaction_count', 0):,}",
                color=Theme.Colors.TEXT_SECONDARY,
            ),
            NumericText(
                _usd(child.get("total")),
                color=ledger_amount_color(child.get("total", 0)),
            ),
            SecondaryText(str(child.get("last_used") or "—")),
        ]
