"""Pure helpers behind the saved-facts section of the AI modal's Memory tab."""

from app.components.frontend.dashboard.modals.user_facts_section import (
    fact_edit_payload,
    fact_row_cells,
)


class TestRowCells:
    def test_cells_are_category_fact_and_age(self) -> None:
        cells = fact_row_cells(
            {
                "category": "finance",
                "fact": "House valued at $711,200 as of August 2026",
                "saved_at": "2026-08-24T03:03:56+00:00",
            },
            now_iso="2026-08-24T05:03:56+00:00",
        )

        assert cells[0] == "finance"
        assert cells[1] == "House valued at $711,200 as of August 2026"
        assert "ago" in cells[2]

    def test_missing_fields_degrade_to_placeholders(self) -> None:
        cells = fact_row_cells({}, now_iso="2026-08-24T05:03:56+00:00")

        assert cells[0] == "general"
        assert cells[1] == ""
        assert cells[2] == "—"


class TestEditPayload:
    def test_payload_trims_and_keeps_category(self) -> None:
        assert fact_edit_payload(fact="  corrected  ", category="finance") == {
            "fact": "corrected",
            "category": "finance",
        }

    def test_blank_fact_is_rejected(self) -> None:
        """An empty edit would silently blank a fact; the caller must be
        told rather than the store quietly losing it."""
        try:
            fact_edit_payload(fact="   ", category="finance")
        except ValueError:
            return
        raise AssertionError("blank fact should raise")
