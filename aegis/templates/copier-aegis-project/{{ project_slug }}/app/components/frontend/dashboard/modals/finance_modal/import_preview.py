"""
Finance Service Detail Modal

A Quicken-style finance workspace, organised into tabs:

* **Accounts** — the register. A left sidebar lists accounts grouped into
  Banking / Credit / Investments / etc., each with its balance and a grand
  total; selecting one shows an account-detail header (with a Manage menu)
  above its transactions (or holdings, for investment accounts). The sidebar
  only lives on this tab.
* **Overview** — a net-worth summary (assets, liabilities, net worth) with a
  per-group breakdown. No sidebar; this is the "home" landing.

Data is fetched async through the internal ``APIClient`` (never a DB session
from the frontend). All colours, spacing, and type come from ``AegisTheme``.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    NumericText,
    PrimaryText,
    SecondaryText,
    SectionCard,
    StatusDot,
    Tag,
)

# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
# One height for every Overview card, so the row has a single baseline.
# Named slices in the spending donut (and rows in the list under it) before
# the tail folds into "Other". Five left "Other" as the biggest slice on any
# real ledger, which hides exactly the breakdown the card exists to show.
# Measured against a real ledger (23 parent-level categories after the
# spending_by_category rollup): 10 slices still left "Other" at 16.3%; 15
# gets it to 5.3%, with everything past #15 individually under 1% of total
# spend - the tail at that point really is "everything else", not a few
# disguised top categories. PieChartCard's legend scrolls within its fixed
# height (modal_sections.py) rather than clipping, so this isn't bounded
# by legend space anymore.
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _PREVIEW_DETAIL_CAP,
    _PREVIEW_DETAIL_HEIGHT,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.modal_sections import (
    MetricCard,
    RankedBar,
    RankedBarCard,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


def _preview_date_range(start: object, end: object) -> str:
    """The span an import covers, short enough to sit on ONE line.

    A metric card's caption is ~175px wide, and the house
    ``format_date`` twice over ("Jul 29, 2026 to Aug 6, 2026") does not
    fit - it wraps, which makes that card taller than the two beside it
    and leaves the row with a ragged bottom edge. Repeating the year is
    what it can afford to lose: a same-year range drops both (the file
    name carries it), a range that crosses one keeps both, because that
    is exactly when the year is the surprising part.
    """
    left, right = format_date(start), format_date(end)
    if not right or left == right:
        return left or right
    if left[-4:].isdigit() and left[-4:] == right[-4:]:
        left = left[:-6]
    return f"{left} to {right}"


def _preview_metric(
    label: str, count: int, caption: str, accent: str, tooltip: str
) -> MetricCard:
    """One outcome of an import, as the house metric card.

    NO icon, though ``MetricCard`` takes one: nothing else in the
    dashboard passes it, and a glyph beside the label reads as a
    different component rather than as emphasis. The label already says
    which of the three this is.

    A zero keeps the muted colour: nothing happened, so nothing should
    catch the eye. ``MetricCard`` leaves its number untinted by design
    (``color`` only ever tints the icon, so here it is inert), and a live
    count claims the colour back through ``set_value`` - three cards is
    few enough that a tinted number still means something, which is the
    condition that rule was written against.
    """
    live = count > 0
    color = accent if live else Theme.Colors.TEXT_SECONDARY
    card = MetricCard(
        label=label,
        value=f"{count:,}",
        color=color,
        prev_value=caption,
        tooltip=tooltip,
    )
    card.set_value(f"{count:,}", color)
    return card


def _preview_dot(text: str, live: bool, accent: str, tooltip: str) -> StatusDot:
    """An import outcome that does NOT touch the ledger, as a status dot.

    The house dot rather than a bordered chip: a chip's outline gives it a
    box of its own, which is the chrome the metric cards above use to say
    "this lands in your ledger". These do not. A zero keeps its dot and
    goes muted, so the row holds its shape either way.
    """
    return StatusDot(text, accent if live else Theme.Colors.TEXT_SECONDARY, tooltip)


def _preview_tag_row(kind: str, name: str, color: str) -> ft.Control:
    """One named thing in a preview section: a kind tag beside its name."""
    return ft.Row(
        [Tag(kind, color=color), SecondaryText(name, no_wrap=True)],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _preview_creates(preview: dict[str, Any]) -> list[ft.Control]:
    """Rows naming what a commit would MINT, not just count.

    An import that quietly invents an account is the surprise this dialog
    exists to head off, so each one is named. Categories are capped: a
    Quicken tree can carry hundreds, and a dialog that scrolls for a page
    stops being read at all.
    """
    rows: list[ft.Control] = []
    rows.extend(
        _preview_tag_row("Account", name, Theme.Colors.WARNING)
        for name in preview.get("new_accounts") or []
    )
    categories = preview.get("new_categories") or []
    rows.extend(
        _preview_tag_row("Category", name, Theme.Colors.TEXT_SECONDARY)
        for name in categories[:_PREVIEW_DETAIL_CAP]
    )
    if len(categories) > _PREVIEW_DETAIL_CAP:
        rows.append(
            SecondaryText(
                f"and {len(categories) - _PREVIEW_DETAIL_CAP:,} more categories",
                size=Theme.Typography.BODY_SMALL,
            )
        )
    return rows


def _preview_edits(preview: dict[str, Any]) -> list[ft.Control]:
    """One row per in-place update: when, how much, what changed.

    An edit is the only outcome here that rewrites something already
    stored, so it is spelled out field by field rather than counted - a
    number alone gives no way to tell a payee tidy-up from a
    re-categorization you did not ask for.
    """
    edits = preview.get("edits") or []
    rows: list[ft.Control] = []
    for edit in edits[:_PREVIEW_DETAIL_CAP]:
        rows.append(
            ft.Row(
                [
                    ft.Container(
                        content=SecondaryText(
                            format_date(edit.get("date")),
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        width=90,
                    ),
                    ft.Container(
                        content=NumericText(
                            _usd(abs(edit.get("amount", 0))),
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        width=80,
                        alignment=ft.alignment.center_right,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                PrimaryText(
                                    edit.get("name") or "transaction",
                                    size=Theme.Typography.BODY_SMALL,
                                    no_wrap=True,
                                ),
                                SecondaryText(
                                    "; ".join(edit.get("changes") or []),
                                    size=Theme.Typography.CAPTION,
                                ),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                        expand=True,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
    if len(edits) > _PREVIEW_DETAIL_CAP:
        rows.append(
            SecondaryText(
                f"and {len(edits) - _PREVIEW_DETAIL_CAP:,} more updates",
                size=Theme.Typography.BODY_SMALL,
            )
        )
    return rows


def import_preview_body(preview: dict[str, Any], file_name: str) -> ft.Column:
    """The body of the import review dialog: what a commit would do.

    Built as house controls rather than a column of sentences, because the
    shape carries the meaning. The three outcomes that CHANGE the ledger
    are metric cards; the two that do not (scheduled, errors) are chips,
    so a skipped row can never be read as an incoming one. The per-account
    split is the ranked-bar card, which answers "where does this land"
    with a glance instead of a list to be added up by eye.

    Pure and module-level so the coverage property - every count the
    preview carries reaches the screen - can be asserted directly.
    """
    added_note = "New transactions"
    if preview.get("rows_inserted", 0) and preview.get("insert_date_start"):
        added_note = _preview_date_range(
            preview.get("insert_date_start"), preview.get("insert_date_end")
        )
    metrics, dot_row = _import_count_controls(
        preview,
        headings=(
            ("To add", added_note),
            ("To update", "Changed in place"),
            ("Already have", "Left alone"),
        ),
    )

    sections: list[ft.Control] = []
    by_account = preview.get("inserts_by_account") or {}
    # One bar is not a ranking, it is "To add" restated.
    if len(by_account) > 1:
        sections.append(
            RankedBarCard(
                title="Where the new rows land",
                rows=[
                    RankedBar(label=name, value=float(count), display=f"{count:,}")
                    for name, count in sorted(
                        by_account.items(), key=lambda item: -item[1]
                    )
                ],
            )
        )
    creates = _preview_creates(preview)
    if creates:
        sections.append(
            SectionCard(
                title="Also creates",
                body=ft.Column(creates, spacing=Theme.Spacing.XS, tight=True),
                body_padding=Theme.Spacing.MD,
            )
        )
    removed = preview.get("removed_accounts") or []
    if removed:
        sections.append(
            SectionCard(
                title="Staying out",
                body=ft.Column(
                    [
                        SecondaryText(
                            "You removed these accounts, so their rows are "
                            "ignored. Re-add an account to import into it "
                            "again.",
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        *(
                            _preview_tag_row(
                                "Account", name, Theme.Colors.TEXT_SECONDARY
                            )
                            for name in removed
                        ),
                    ],
                    spacing=Theme.Spacing.XS,
                    tight=True,
                ),
                body_padding=Theme.Spacing.MD,
            )
        )
    edits = _preview_edits(preview)
    if edits:
        sections.append(
            SectionCard(
                title="Updated in place",
                body=ft.Column(edits, spacing=Theme.Spacing.XS, tight=True),
                body_padding=Theme.Spacing.MD,
            )
        )

    children: list[ft.Control] = [
        SecondaryText(
            f"{preview.get('rows_total', 0):,} rows read from {file_name}",
            size=Theme.Typography.BODY_SMALL,
        ),
        metrics,
        dot_row,
    ]
    if sections:
        children.append(
            ft.Container(
                content=ft.Column(
                    sections,
                    spacing=Theme.Spacing.SM,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                height=_PREVIEW_DETAIL_HEIGHT,
            )
        )
    children.append(_import_footnote("Nothing has been written yet."))
    return ft.Column(children, spacing=Theme.Spacing.MD, tight=True)


def _import_count_controls(
    counts: dict[str, Any],
    *,
    headings: tuple[tuple[str, str], tuple[str, str], tuple[str, str]],
) -> tuple[ft.Row, ft.Row]:
    """(the three cards, the row of dots) for one set of import counts.

    Shared by the review dialog and the completion summary. They show the
    SAME five numbers, before and after, and a reader compares the two
    screens - so they are one layout wearing two sets of labels, not two
    layouts that drift into disagreeing about what a count means.

    ``headings`` supplies (label, caption) for add / update / duplicate,
    which is the whole difference between them: the review says what will
    happen, the summary says what did.
    """
    inserted = counts.get("rows_inserted", 0)
    updated = counts.get("rows_updated", 0)
    duplicate = counts.get("rows_duplicate", 0)
    skipped = counts.get("rows_skipped", 0)
    errors = counts.get("rows_error", 0)
    (add_label, add_note), (edit_label, edit_note), (have_label, have_note) = headings

    metrics = ft.Row(
        [
            _preview_metric(
                add_label,
                inserted,
                add_note,
                Theme.Colors.SUCCESS,
                "New transactions this file carries that your ledger does not.",
            ),
            _preview_metric(
                edit_label,
                updated,
                edit_note,
                Theme.Colors.WARNING,
                "Edited in your source app; changed in place, not duplicated.",
            ),
            _preview_metric(
                have_label,
                duplicate,
                have_note,
                Theme.Colors.TEXT_SECONDARY,
                "Matches a transaction already stored, so it is skipped.",
            ),
        ],
        spacing=Theme.Spacing.MD,
    )

    ignored = counts.get("rows_ignored", 0)
    dots: list[ft.Control] = [
        _preview_dot(
            f"{skipped:,} scheduled",
            bool(skipped),
            Theme.Colors.WARNING,
            "Not yet posted. Each one imports on its own once the payment clears.",
        ),
        *(
            [
                _preview_dot(
                    f"{ignored:,} from removed accounts",
                    True,
                    Theme.Colors.TEXT_SECONDARY,
                    "You removed these accounts, so their rows stay out. "
                    "Re-add the account to opt back in.",
                )
            ]
            if ignored
            else []
        ),
        _preview_dot(
            f"{errors:,} {'error' if errors == 1 else 'errors'}",
            bool(errors),
            Theme.Colors.ERROR,
            "Rows that could not be placed in an account.",
        ),
    ]
    kept = counts.get("category_kept_count", 0)
    if kept:
        # A dot too: three asides in one row read as one kind of thing,
        # and this is the same kind - something the import did NOT do to
        # the ledger.
        dots.append(
            _preview_dot(
                f"{kept:,} {'category' if kept == 1 else 'categories'} kept",
                True,
                Theme.Colors.SUCCESS,
                "You set these by hand, so the import leaves them as you set them.",
            )
        )
    return metrics, ft.Row(dots, spacing=Theme.Spacing.MD, wrap=True)


def _import_footnote(text: str) -> ft.Control:
    """The muted closing line all three import dialogs end on.

    The note EXPANDS. A Row hands its children unbounded width, so a note
    long enough to need a second line runs off the panel mid-sentence
    instead of wrapping inside it. START, not CENTER: centred against a
    two-line note the icon floats into the gap between the lines.
    """
    return ft.Row(
        [
            ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=Theme.Colors.TEXT_SECONDARY),
            ft.Container(
                content=SecondaryText(text, size=Theme.Typography.BODY_SMALL),
                expand=True,
            ),
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )
