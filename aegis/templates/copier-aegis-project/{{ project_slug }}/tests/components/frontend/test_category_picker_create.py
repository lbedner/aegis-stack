"""Creating a category from the picker that needed one.

Withheld on purpose for a long time, and the reasoning was sound:
"inventing categories inline is how a category list turns into 400
near-duplicates". What changed is that the resolver behind it is
get-or-CREATE, keyed on a normalized slug - so "kids: activities" lands
on "Kids:Activities" instead of beside it, and a third path segment folds
back to two. The guard lives in the service, so the affordance no longer
has to be the guard.

It stays OPT-IN. A picker whose caller has nowhere to put a new category
must not offer to make one.
"""

from app.components.frontend.controls.pickers import CategoryPickerButton

CATEGORIES = [("1", "Auto & Transport:Gas & Fuel"), ("2", "Kids:Toys")]


def _rows(picker: CategoryPickerButton, query: str) -> list[str]:
    picker._render_rows(query)
    texts: list[str] = []

    def walk(node: object) -> None:
        value = getattr(node, "value", None)
        if isinstance(value, str) and value:
            texts.append(value)
        content = getattr(node, "content", None)
        if content is not None:
            walk(content)
        for child in getattr(node, "controls", None) or []:
            walk(child)

    for row in picker._rows_column.controls:
        walk(row)
    return texts


class TestTheCreateAffordance:
    def test_it_offers_to_create_what_you_typed(self) -> None:
        picker = CategoryPickerButton(
            categories=CATEGORIES,
            on_pick=lambda _ids, _key: None,
            on_create=lambda _ids, _text: None,
        )

        assert '+ Create "Kids:Activities"' in _rows(picker, "Kids:Activities")

    def test_it_does_not_offer_to_recreate_something_that_exists(self) -> None:
        """The first defence against near-duplicates is not showing the
        door when the row is already there."""
        picker = CategoryPickerButton(
            categories=CATEGORIES,
            on_pick=lambda _ids, _key: None,
            on_create=lambda _ids, _text: None,
        )

        rows = _rows(picker, "Kids:Toys")
        assert not any(r.startswith("+ Create") for r in rows)
        assert "Kids:Toys" in rows

    def test_a_picker_without_the_callback_offers_nothing(self) -> None:
        """Every other call site keeps the old behaviour: no callback, no
        create row, so a picker that cannot save one cannot suggest one."""
        picker = CategoryPickerButton(
            categories=CATEGORIES,
            on_pick=lambda _ids, _key: None,
        )

        rows = _rows(picker, "Kids:Activities")
        assert not any(r.startswith("+ Create") for r in rows)

    def test_the_create_row_hands_back_the_typed_text(self) -> None:
        seen: list[tuple[list[int], str]] = []
        picker = CategoryPickerButton(
            categories=CATEGORIES,
            on_pick=lambda _ids, _key: None,
            on_create=lambda ids, text: seen.append((ids, text)),
        )
        picker._active_ids = [7, 8, 9]

        picker._create("Kids:Activities")

        assert seen == [([7, 8, 9], "Kids:Activities")]
