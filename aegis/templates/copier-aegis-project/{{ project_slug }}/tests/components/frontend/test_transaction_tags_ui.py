"""Tags in the register: the user-defined flag, on screen.

Three surfaces, one mechanism. The bulk-selection row applies a tag to
whatever is checked (the picker's create row means the first flag is
typed, not configured); each row wears its tags as chips beside the
payee; clicking a chip filters the register to that tag, and the row's
inline expand is where a tag comes OFF.
"""

import flet as ft

from app.components.frontend.controls.pickers import TagPickerButton
from app.components.frontend.controls.tag import Tag
from app.components.frontend.dashboard.modals.finance_modal import (
    _transaction_expanded_content,
    transaction_tag_chips,
)
from app.components.frontend.theme import AegisTheme as Theme
from tests.components.frontend._tree import texts as _texts
from tests.components.frontend._tree import walk as _walk

FLAGGED = {"id": 7, "name": "Flagged", "color": None}
TAX = {"id": 8, "name": "Tax 2026", "color": "#F5A623"}


class TestRowChips:
    def test_chips_carry_the_names(self) -> None:
        chips = transaction_tag_chips([FLAGGED, TAX])
        rendered = " ".join(t for chip in chips for t in _texts(chip))
        assert "Flagged" in rendered
        assert "Tax 2026" in rendered

    def test_a_tag_color_is_worn_and_the_default_is_accent(self) -> None:
        chips = transaction_tag_chips([FLAGGED, TAX])
        tags = [n for chip in chips for n in _walk(chip) if isinstance(n, Tag)]
        assert tags[0].border.top.color == Theme.Colors.ACCENT
        assert tags[1].border.top.color == "#F5A623"

    def test_the_cap_folds_the_tail_into_a_count(self) -> None:
        """A register row is one line; three tags cannot widen it."""
        many = [FLAGGED, TAX, {"id": 9, "name": "Trip", "color": None}]
        chips = transaction_tag_chips(many, cap=2)
        rendered = " ".join(t for chip in chips for t in _texts(chip))
        assert "Flagged" in rendered and "Tax 2026" in rendered
        assert "Trip" not in rendered
        assert "+1" in rendered

    def test_no_tags_no_controls(self) -> None:
        assert transaction_tag_chips([]) == []

    def test_compact_chips_are_actually_smaller(self) -> None:
        """The register column is dense; its chips shrink so a name like
        "Marisa" fits inside the pill instead of overflowing it."""

        def _chip_text(chips):
            return next(
                n
                for chip in chips
                for n in _walk(chip)
                if isinstance(getattr(n, "value", None), str) and n.value
            )

        regular = _chip_text(transaction_tag_chips([FLAGGED]))
        compact = _chip_text(transaction_tag_chips([FLAGGED], compact=True))
        assert compact.size < regular.size

    def test_chips_are_clickable_when_a_tap_handler_is_given(self) -> None:
        seen: list[dict] = []
        chips = transaction_tag_chips([FLAGGED], on_tap=seen.append)
        clickable = [
            n for chip in chips for n in _walk(chip) if getattr(n, "on_click", None)
        ]
        assert clickable
        clickable[0].on_click(None)
        assert seen == [FLAGGED]


class TestExpandedDetail:
    TXN = {"id": 3, "name": "Purchase", "amount": -1_000, "tags": [FLAGGED]}

    def test_tags_appear_with_a_remove_affordance(self) -> None:
        removed: list[tuple[dict, dict]] = []
        content = _transaction_expanded_content(
            self.TXN, on_remove_tag=lambda txn, tag: removed.append((txn, tag))
        )
        assert "Flagged" in " ".join(_texts(content))
        closes = [
            n
            for n in _walk(content)
            if getattr(n, "icon", None) == ft.Icons.CLOSE
            and getattr(n, "on_click", None)
        ]
        assert closes
        closes[0].on_click(None)
        assert removed == [(self.TXN, FLAGGED)]

    def test_an_untagged_row_shows_no_tags_block(self) -> None:
        content = _transaction_expanded_content(
            {**self.TXN, "tags": []}, on_remove_tag=lambda txn, tag: None
        )
        assert "Tags" not in " ".join(_texts(content))


class TestPicker:
    def test_the_picker_offers_to_create_what_you_typed(self) -> None:
        picker = TagPickerButton(
            tags=[("Flagged", "Flagged")],
            on_pick=lambda ids, key: None,
            on_create=lambda ids, text: None,
        )
        picker._render_rows("Tax 2026")
        rendered = " ".join(
            t for row in picker._rows_column.controls for t in _texts(row)
        )
        assert 'Create "Tax 2026"' in rendered


class TestRegisterWiring:
    """The panel actually uses the pieces: a Tags COLUMN of compact chips
    (not squatting in the payee cell), a Tag bulk action, and a
    tag_id-filtered fetch."""

    def test_the_panel_wires_the_feature(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.TransactionsPanel)
        assert "transaction_tag_chips(" in source
        assert "compact=True" in source
        assert "_tag_picker" in source
        assert "tag_id" in source
        assert "_bulk_tag_trigger" in source

    def test_every_transaction_editor_offers_tag(self) -> None:
        """The register is not special: the two Review work queues edit
        transactions too (category, payee), so the Tag verb rides their
        selection rows as well - one mechanism, every editor."""
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        for panel in (
            finance_modal.TransactionsPanel,
            finance_modal.UncategorizedPanel,
            finance_modal.NoPayeePanel,
        ):
            source = inspect.getsource(panel)
            assert "_bulk_tag_trigger" in source, panel.__name__
            assert "_tag_picker" in source, panel.__name__

    def test_the_apply_and_fetch_paths_are_shared(self) -> None:
        """Three panels tag; ONE mixin owns the apply path and one POST
        helper serves it - the panels differ only in what opens the
        picker. Stronger than the original source-grep: the panels no
        longer carry their own copies at all."""
        from app.components.frontend.dashboard.modals import finance_modal
        from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
            TagApplyMixin,
        )

        assert callable(finance_modal.fetch_tag_options)
        assert callable(finance_modal.post_tag)
        for panel in (
            finance_modal.TransactionsPanel,
            finance_modal.UncategorizedPanel,
            finance_modal.NoPayeePanel,
        ):
            assert TagApplyMixin in panel.__mro__, panel.__name__
            # and none of them re-declares the verb locally
            assert "_apply_tag" not in vars(panel), panel.__name__

    def test_every_trigger_gets_the_selection_count(self) -> None:
        """A BulkActionTrigger is INVISIBLE until set_count() is called -
        a trigger added to the row but skipped in the selection handler
        simply never appears (confirmed live: Tag and Delete were in the
        layout and never on screen)."""
        import inspect
        import re

        from app.components.frontend.dashboard.modals import finance_modal

        for panel in (
            finance_modal.TransactionsPanel,
            finance_modal.UncategorizedPanel,
            finance_modal.NoPayeePanel,
        ):
            source = inspect.getsource(panel)
            triggers = set(re.findall(r"self\.(_bulk\w*trigger)\s*=", source))
            counted = set(re.findall(r"self\.(_bulk\w*trigger)\.set_count\(", source))
            assert triggers == counted, (panel.__name__, triggers - counted)

    def test_the_register_offers_delete_behind_a_confirmation(self) -> None:
        """Delete rides the selection row like the other bulk verbs, but
        being the one irreversible-feeling verb it goes through
        ConfirmDialog (destructive red confirm) and restates the count
        and dollar sum the selection label already shows."""
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.TransactionsPanel)
        assert "_bulk_delete_trigger" in source
        delete_handler = inspect.getsource(
            finance_modal.TransactionsPanel._open_bulk_delete
        )
        assert "ConfirmDialog(" in delete_handler
        assert "destructive=True" in delete_handler

    def test_the_tags_cell_rides_its_own_column(self) -> None:
        """Both row shapes fill the Tags cell - a trade row skipping it
        would shift every later cell one column left, the same silent
        misalignment the Account column's tests pin."""
        import inspect
        import re

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.TransactionsPanel)
        assert len(re.findall(r"_tags_cell\(record\)", source)) == 2
        # The chips no longer ride the payee cell.
        payee_cell = source[source.index("def _payee_cell") :]
        payee_cell = payee_cell[: payee_cell.index("def _account_cell")]
        assert "transaction_tag_chips" not in payee_cell
