"""The import dialogs' bodies: the review, and the completion summary.

The review is the last thing between a file and several thousand rows of
someone's money, so the property pinned here is COVERAGE: every count the
preview carries has to reach the screen. A count the builder silently
drops does not look broken, it looks like "that will not happen" - which
is the one way this dialog can lie.

The second property is that the counts which change the ledger look
different from the counts which do not. Add / update / already-have are
cards; scheduled and errors are dots. Reading a skipped row as an
incoming one is the same mistake in the other direction.

The third is that the two dialogs agree. They show the SAME five numbers,
before and after, and a reader compares them - so they are built from one
shared layout rather than two that drift.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    PrimaryText,
    SecondaryText,
    StatusDot,
    Tag,
)
from app.components.frontend.dashboard.modals.finance_modal import (
    import_identical_body,
    import_preview_body,
    import_summary_body,
    investment_import_preview_body,
    investment_target_options,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    MetricCard,
    RankedBarCard,
)
from app.components.frontend.theme import AegisTheme as Theme
from tests.components.frontend._tree import texts as _texts
from tests.components.frontend._tree import walk as _walk


def _of_type(node: ft.Control, kind: type) -> list[Any]:
    return [c for c in _walk(node) if isinstance(c, kind)]


def _card_label(card: MetricCard) -> str:
    """A MetricCard's label is the first text it renders."""
    return _texts(card)[0]


def _dots(node: ft.Control) -> dict[str, str]:
    """label -> colour for every house status dot in the tree."""
    return {dot.label: dot.color for dot in _of_type(node, StatusDot)}


PREVIEW: dict[str, Any] = {
    "rows_total": 18343,
    "rows_inserted": 32,
    "rows_updated": 4,
    "rows_duplicate": 18261,
    "rows_skipped": 50,
    "rows_error": 2,
    "insert_date_start": "2026-07-29",
    "insert_date_end": "2026-08-06",
    "inserts_by_account": {
        "TOTAL CHECKING (CHASE)": 13,
        "AMEX": 9,
        "CLASSIC CHECKING (HVCU)": 7,
        "Citizens Bank Mortgage": 1,
    },
    "new_accounts": ["CHASE SAVINGS"],
    "new_categories": ["Bills & Utilities:Streaming"],
    "category_kept_count": 3,
    "edits": [
        {
            "transaction_id": 1,
            "date": "2026-08-01",
            "amount": -2486,
            "name": "Netflix",
            "changes": ["name: 'NETFLIX.COM' -> 'Netflix'"],
        }
    ],
}


class TestCoverage:
    def test_every_count_reaches_the_screen(self) -> None:
        """The whole point of a dry run. A dropped count is a lie of
        omission, and this dialog's job is to have none."""
        body = import_preview_body(PREVIEW, "export.csv")
        rendered = " ".join(_texts(body))
        for count in (32, 4, 18261, 50, 2, 18343):
            assert f"{count:,}" in rendered, f"{count:,} missing from the body"

    def test_the_file_name_is_shown(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        assert any("export.csv" in text for text in _texts(body))

    def test_new_accounts_and_categories_are_named(self) -> None:
        """A commit that quietly mints an account is the complaint this
        dialog exists to answer, so the names go on screen, not a count."""
        rendered = " ".join(_texts(import_preview_body(PREVIEW, "export.csv")))
        assert "CHASE SAVINGS" in rendered
        assert "Bills & Utilities:Streaming" in rendered


class TestLedgerChangingCountsAreCards:
    def test_the_three_ledger_outcomes_are_metric_cards(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        labels = [_card_label(c) for c in _of_type(body, MetricCard)]
        assert labels == ["To add", "To update", "Already have"]

    def test_each_card_carries_its_own_count(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        values = [c.value_text.value for c in _of_type(body, MetricCard)]
        assert values == ["32", "4", "18,261"]

    def test_scheduled_and_errors_are_dots_not_cards(self) -> None:
        """A skipped row must not wear the same chrome as one that lands:
        a card is the dialog's way of saying "this reaches your ledger",
        and neither of these does."""
        body = import_preview_body(PREVIEW, "export.csv")
        labels = [_card_label(c) for c in _of_type(body, MetricCard)]
        assert not any("cheduled" in label or "rror" in label for label in labels)
        assert "50 scheduled" in _dots(body)
        assert "2 errors" in _dots(body)

    def test_the_asides_are_not_bordered_chips(self) -> None:
        """A chip's outline is a box, which is the metric cards' own
        signal. Tag stays for the "Account" / "Category" kind markers."""
        body = import_preview_body(PREVIEW, "export.csv")
        tagged = [t for tag in _of_type(body, Tag) for t in _texts(tag)]
        assert not any("scheduled" in t or "error" in t or "kept" in t for t in tagged)

    def test_a_preserved_category_is_a_dot_too(self) -> None:
        """One row, one kind of thing."""
        assert "3 categories kept" in _dots(import_preview_body(PREVIEW, "export.csv"))

    def test_a_dot_is_muted_at_zero_and_coloured_when_live(self) -> None:
        live = _dots(import_preview_body(PREVIEW, "export.csv"))
        assert live["50 scheduled"] == Theme.Colors.WARNING
        assert live["2 errors"] == Theme.Colors.ERROR
        quiet = _dots(
            import_preview_body(
                {**PREVIEW, "rows_skipped": 0, "rows_error": 0}, "export.csv"
            )
        )
        assert quiet["0 scheduled"] == Theme.Colors.TEXT_SECONDARY
        assert quiet["0 errors"] == Theme.Colors.TEXT_SECONDARY


class TestCardsMatchEveryOtherCard:
    def test_the_metric_cards_carry_no_icon(self) -> None:
        """``MetricCard`` takes an icon, and across the whole dashboard
        exactly nothing passes one. A card with a glyph beside its label
        does not read as emphasis, it reads as a different component -
        and the label already says which of the three this is.
        """
        body = import_preview_body(PREVIEW, "export.csv")
        for card in _of_type(body, MetricCard):
            assert not _of_type(card, ft.Icon), f"{_card_label(card)} grew an icon"


class TestRemovedAccountsStayVisible:
    """An ignored row must not vanish: the dot counts them and the
    Staying-out section names the account, or the reader concludes the
    import simply lost 23 rows."""

    IGNORING = {**PREVIEW, "rows_ignored": 23, "removed_accounts": ["X017 AUDI A6"]}

    def test_the_dot_counts_the_ignored_rows(self) -> None:
        dots = _dots(import_preview_body(self.IGNORING, "export.csv"))
        assert "23 from removed accounts" in dots

    def test_no_ignored_rows_no_dot(self) -> None:
        dots = _dots(import_preview_body(PREVIEW, "export.csv"))
        assert not any("removed" in label for label in dots)

    def test_the_section_names_the_account(self) -> None:
        body = import_preview_body(self.IGNORING, "export.csv")
        rendered = " ".join(_texts(body))
        assert "Staying out" in rendered
        assert "X017 AUDI A6" in rendered

    def test_the_summary_carries_the_count_too(self) -> None:
        summary = import_summary_body({**self.IGNORING, "rows_total": 100})
        assert "23 from removed accounts" in _dots(summary)


class TestColorCarriesMeaning:
    def test_a_live_count_takes_its_accent(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        add, update, _have = _of_type(body, MetricCard)
        assert add.value_text.color == Theme.Colors.SUCCESS
        assert update.value_text.color == Theme.Colors.WARNING

    def test_a_zero_stays_muted(self) -> None:
        """Nothing happened, so nothing should catch the eye - a coloured
        zero is an alarm for a non-event."""
        quiet = {**PREVIEW, "rows_updated": 0, "rows_error": 0}
        body = import_preview_body(quiet, "export.csv")
        _add, update, _have = _of_type(body, MetricCard)
        assert update.value_text.color == Theme.Colors.TEXT_SECONDARY

    def test_already_have_is_never_accented(self) -> None:
        """The biggest number in the dialog is also the least interesting:
        it is what did NOT happen."""
        body = import_preview_body(PREVIEW, "export.csv")
        *_, have = _of_type(body, MetricCard)
        assert have.value_text.color == Theme.Colors.TEXT_SECONDARY


class TestAccountBreakdown:
    def test_accounts_are_ranked_largest_first(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        cards = _of_type(body, RankedBarCard)
        assert len(cards) == 1
        rendered = _texts(cards[0])
        assert rendered.index("TOTAL CHECKING (CHASE)") < rendered.index("AMEX")
        assert rendered.index("AMEX") < rendered.index("Citizens Bank Mortgage")

    def test_each_account_shows_its_own_count(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        rendered = _texts(_of_type(body, RankedBarCard)[0])
        for count in ("13", "9", "7", "1"):
            assert count in rendered

    def test_a_single_account_gets_no_breakdown(self) -> None:
        """One bar is not a ranking, it is a restatement of "To add"."""
        single = {**PREVIEW, "inserts_by_account": {"AMEX": 32}}
        assert not _of_type(import_preview_body(single, "export.csv"), RankedBarCard)


class TestLayoutStaysBounded:
    def test_no_stretch_row_without_a_bounded_height(self) -> None:
        """A Row that stretches its children needs a height to stretch TO.

        Given an unbounded one - a ``tight`` Column is unbounded - Flutter
        cannot lay the Row out, and Flet's release build paints NOTHING
        rather than an error: the dialog opened with its title, its
        subtitle, and then a tall empty panel. Silent, and invisible to
        every other test here, since the control tree it asserts on is
        built correctly and simply never renders.
        """
        for row in _of_type(import_preview_body(PREVIEW, "export.csv"), ft.Row):
            if row.vertical_alignment != ft.CrossAxisAlignment.STRETCH:
                continue
            assert row.height is not None or row.expand, (
                "a STRETCH Row needs height= or expand=, or it renders blank"
            )


class TestDateRange:
    def test_a_same_year_range_drops_the_repeated_year(self) -> None:
        """Two full dates overflow a card's caption and wrap, which makes
        that card taller than the two beside it."""
        body = import_preview_body(PREVIEW, "export.csv")
        add, *_ = _of_type(body, MetricCard)
        assert "Jul 29 to Aug 6, 2026" in _texts(add)

    def test_a_range_crossing_a_year_keeps_both(self) -> None:
        """Exactly when the year is the surprising part."""
        crossing = {
            **PREVIEW,
            "insert_date_start": "2025-12-28",
            "insert_date_end": "2026-01-03",
        }
        add, *_ = _of_type(import_preview_body(crossing, "export.csv"), MetricCard)
        assert "Dec 28, 2025 to Jan 3, 2026" in _texts(add)

    def test_a_single_day_is_not_written_as_a_range(self) -> None:
        same = {
            **PREVIEW,
            "insert_date_start": "2026-08-06",
            "insert_date_end": "2026-08-06",
        }
        add, *_ = _of_type(import_preview_body(same, "export.csv"), MetricCard)
        assert "Aug 6, 2026" in _texts(add)
        assert not any(" to " in text for text in _texts(add))

    def test_no_inserts_says_so_instead_of_a_range(self) -> None:
        empty = {**PREVIEW, "rows_inserted": 0}
        add, *_ = _of_type(import_preview_body(empty, "export.csv"), MetricCard)
        assert "New transactions" in _texts(add)


class TestNothingWrittenYet:
    def test_the_body_says_nothing_has_been_written(self) -> None:
        body = import_preview_body(PREVIEW, "export.csv")
        assert any("Nothing has been written" in t for t in _texts(body))

    def test_an_empty_preview_still_builds(self) -> None:
        """A file that changes nothing still opens this dialog; a builder
        that needs a non-empty preview would raise instead of saying so."""
        body = import_preview_body({"rows_total": 0}, "empty.csv")
        assert [c.value_text.value for c in _of_type(body, MetricCard)] == [
            "0",
            "0",
            "0",
        ]


RESULT: dict[str, Any] = {
    "batch_id": 8,
    "rows_total": 18343,
    "rows_inserted": 32,
    "rows_updated": 4,
    "rows_duplicate": 18261,
    "rows_skipped": 50,
    "rows_error": 2,
}


class TestSummary:
    def test_it_speaks_in_the_past_tense(self) -> None:
        """The review says what WILL happen; by the time this opens it
        already has."""
        labels = [
            _card_label(c) for c in _of_type(import_summary_body(RESULT), MetricCard)
        ]
        assert labels == ["Added", "Updated", "Already had"]

    def test_every_count_reaches_the_screen(self) -> None:
        rendered = " ".join(_texts(import_summary_body(RESULT)))
        for count in (32, 4, 18261, 50, 2, 18343):
            assert f"{count:,}" in rendered, f"{count:,} missing from the summary"

    def test_scheduled_and_errors_are_dots_here_too(self) -> None:
        dots = _dots(import_summary_body(RESULT))
        assert dots["50 scheduled"] == Theme.Colors.WARNING
        assert dots["2 errors"] == Theme.Colors.ERROR

    def test_the_cards_carry_no_icon(self) -> None:
        for card in _of_type(import_summary_body(RESULT), MetricCard):
            assert not _of_type(card, ft.Icon)

    def test_it_does_not_claim_nothing_was_written(self) -> None:
        """The review's footer reassures you it has not run yet. Carrying
        that line over would be a lie: this dialog opens BECAUSE it ran."""
        assert not any(
            "Nothing has been written" in t for t in _texts(import_summary_body(RESULT))
        )


class TestTheTwoDialogsAgree:
    def test_the_same_numbers_land_on_the_same_cards(self) -> None:
        """A reader compares these two screens. Two layouts built from one
        set of counts must not drift into disagreeing about them."""
        preview_values = [
            c.value_text.value
            for c in _of_type(import_preview_body(RESULT, "export.csv"), MetricCard)
        ]
        summary_values = [
            c.value_text.value
            for c in _of_type(import_summary_body(RESULT), MetricCard)
        ]
        assert preview_values == summary_values == ["32", "4", "18,261"]

    def test_the_same_asides_are_dots_on_both(self) -> None:
        assert set(_dots(import_summary_body(RESULT))) <= set(
            _dots(import_preview_body(RESULT, "export.csv"))
        )

    def test_both_colour_a_live_count_the_same_way(self) -> None:
        preview_add, *_ = _of_type(
            import_preview_body(RESULT, "export.csv"), MetricCard
        )
        summary_add, *_ = _of_type(import_summary_body(RESULT), MetricCard)
        assert preview_add.value_text.color == summary_add.value_text.color

    def test_an_all_zero_result_still_builds(self) -> None:
        body = import_summary_body({"rows_total": 0})
        assert [c.value_text.value for c in _of_type(body, MetricCard)] == [
            "0",
            "0",
            "0",
        ]


class TestIdenticalFile:
    """The third state of the same dialog: a file already imported, byte
    for byte. It is a dead end - one button, nothing to decide - so it
    stays small, but it belongs to the same family and uses the same
    vocabulary rather than falling back to a paragraph of prose."""

    IDENTICAL: dict[str, Any] = {"rows_total": 18343, "identical_batch_id": 7}

    def test_it_names_the_file_and_the_row_count(self) -> None:
        rendered = " ".join(_texts(import_identical_body(self.IDENTICAL, "export.csv")))
        assert "export.csv" in rendered
        assert "18,343" in rendered

    def test_the_outcome_is_dots_not_cards(self) -> None:
        """Nothing lands, so nothing earns a card. A row of zeroes in the
        chrome that means "this reaches your ledger" says the opposite of
        what happened."""
        body = import_identical_body(self.IDENTICAL, "export.csv")
        assert not _of_type(body, MetricCard)
        assert "0 changes" in _dots(body)

    def test_the_dots_are_muted(self) -> None:
        """A no-op is not a warning. Nothing here should catch the eye."""
        for _label, color in _dots(
            import_identical_body(self.IDENTICAL, "e.csv")
        ).items():
            assert color == Theme.Colors.TEXT_SECONDARY

    def test_it_says_nothing_was_written(self) -> None:
        rendered = " ".join(_texts(import_identical_body(self.IDENTICAL, "export.csv")))
        assert "Nothing has been written" in rendered

    def test_it_explains_why_there_is_nothing_to_do(self) -> None:
        """ "0 changes" alone reads as a failed import. The reason - you
        already imported this exact file - is the whole message."""
        rendered = " ".join(_texts(import_identical_body(self.IDENTICAL, "export.csv")))
        assert "already imported" in rendered.lower()


class TestTheFootnoteWraps:
    """A note in a Row gets unbounded width, so it runs off the panel
    instead of wrapping inside it. The review dialog's note is short
    enough to have hidden this; the identical-file one is not, and ran
    clean off the right edge mid-sentence.

    Pinned structurally rather than by measuring text: the fix is that
    the note is width-constrained by an expanding parent, and that is
    exactly what would get dropped by an innocent-looking refactor.
    """

    def _footnote_rows(self, body: ft.Control) -> list[ft.Row]:
        return [
            row
            for row in _of_type(body, ft.Row)
            if any(
                isinstance(c, ft.Icon) and c.name == ft.Icons.INFO_OUTLINE
                for c in (row.controls or [])
            )
        ]

    def test_every_dialog_constrains_its_footnote(self) -> None:
        for body in (
            import_preview_body(PREVIEW, "export.csv"),
            import_identical_body(
                {"rows_total": 18343, "identical_batch_id": 7}, "export.csv"
            ),
        ):
            rows = self._footnote_rows(body)
            assert rows, "no footnote found"
            for row in rows:
                assert any(getattr(c, "expand", None) for c in (row.controls or [])), (
                    "the footnote text is unbounded and will overflow"
                )

    def test_the_icon_sits_with_the_first_line(self) -> None:
        """Centred against a note that wraps to two lines, the icon
        floats into the gap between them."""
        body = import_identical_body(
            {"rows_total": 18343, "identical_batch_id": 7}, "export.csv"
        )
        for row in self._footnote_rows(body):
            assert row.vertical_alignment == ft.CrossAxisAlignment.START


class TestInvestmentTargetOptions:
    """The account picker inside the investment-import dialog: existing
    brokerage accounts plus a create-new entry, never a dead end."""

    ACCOUNTS = [
        {"id": 1, "name": "Chase Checking", "account_type": "checking"},
        {"id": 2, "name": "Traditional IRA", "account_type": "brokerage"},
        {"id": 3, "name": "HSA Investments", "account_type": "brokerage"},
        {"id": 4, "name": "House", "account_type": "property"},
    ]

    def test_only_investment_accounts_are_offered(self) -> None:
        options, _default = investment_target_options(self.ACCOUNTS, None)
        labels = [label for _key, label in options]
        assert "Traditional IRA" in labels
        assert "HSA Investments" in labels
        assert "Chase Checking" not in labels
        assert "House" not in labels

    def test_create_new_is_always_offered(self) -> None:
        options, default = investment_target_options([], None)
        assert options == [("new", "Create a new account...")]
        # With nothing to pick, creating is the default, not an error.
        assert default == "new"

    def test_selected_brokerage_account_is_the_default(self) -> None:
        _options, default = investment_target_options(self.ACCOUNTS, 3)
        assert default == "3"

    def test_selected_non_investment_account_defaults_to_new(self) -> None:
        # Importing a ledger while a checking account happens to be
        # selected must not aim the trades at the checking account.
        _options, default = investment_target_options(self.ACCOUNTS, 1)
        assert default == "new"


class TestInvestmentPreviewBody:
    """The ledger preview rows: name in primary ink, shares muted, value
    as the right-aligned figure - and a total, because 'how much is in
    there' is the first question a finance import should answer."""

    PREVIEW = {
        "activities_parsed": 7,
        "first_date": "2022-02-17",
        "last_date": "2024-12-13",
        "total_value": 373_230,
        "positions": [
            {"name": "Schwab Small Cap Index", "shares": 55.85, "value": 212_230},
            {"name": "Vanguard Total Int Stk Idx Adm", "shares": 0.0, "value": 0},
        ],
    }

    def _texts(self, control) -> list:
        if control is None:
            return []
        found = [control] if hasattr(control, "value") else []
        for child in getattr(control, "controls", None) or []:
            found.extend(self._texts(child))
        found.extend(self._texts(getattr(control, "content", None)))
        return found

    def test_total_value_closes_the_column_in_teal(self) -> None:
        body = investment_import_preview_body(self.PREVIEW)
        texts = [t for t in self._texts(body) if isinstance(t.value, str)]
        total = next(t for t in texts if t.value == "$3,732.30")
        assert total.color == Theme.Colors.ACCENT
        # Under the rows, not in the header: the total is the LAST value
        # rendered, where the eye lands after scanning the column.
        values = [t.value for t in texts]
        assert values.index("$3,732.30") > values.index("$2,122.30")

    def test_name_is_primary_and_shares_are_secondary(self) -> None:
        body = investment_import_preview_body(self.PREVIEW)
        texts = self._texts(body)
        name = next(t for t in texts if t.value == "Schwab Small Cap Index")
        shares = next(t for t in texts if t.value == "55.850 shares")
        value = next(t for t in texts if t.value == "$2,122.30")
        assert isinstance(name, PrimaryText)
        assert shares.color == Theme.Colors.TEXT_SECONDARY
        assert not isinstance(value, SecondaryText)
