"""The property-details surface: which accounts offer it, and what it sends."""

from datetime import date

import pytest

from app.components.frontend.dashboard.modals.finance_modal.account_header import (
    manage_menu_labels,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
    property_payload,
)


class TestManageMenu:
    def test_a_property_account_offers_property_details(self) -> None:
        labels = manage_menu_labels(
            {"account_type": "property", "is_manual": True}
        )

        assert "Property details" in labels

    def test_a_cash_account_does_not(self) -> None:
        labels = manage_menu_labels(
            {"account_type": "checking", "is_manual": True}
        )

        assert "Property details" not in labels
        assert "Rename" in labels  # the ordinary items are untouched

    def test_a_connected_account_still_hides_remove(self) -> None:
        """Provider accounts belong to the bank connection; the existing
        rule survives the new item."""
        labels = manage_menu_labels(
            {"account_type": "property", "is_manual": False}
        )

        assert "Remove" not in labels
        assert "Property details" in labels


class TestFieldsAreUsable:
    """A Container-based form control with no width collapses inside a Row:
    the Type dropdown rendered as a bare label and Value-from vanished
    entirely. Widths are part of the control being usable, not styling."""

    def test_every_field_declares_a_width(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
            property_fields,
        )

        fields = property_fields({})

        for name, control in fields.items():
            assert getattr(control, "width", None), f"{name} has no width"

    def test_stored_values_prefill_the_form(self) -> None:
        """The dialog is an edit surface. Dates that always open blank make
        every save look like a fresh entry and invite retyping."""
        from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
            property_fields,
        )

        fields = property_fields(
            {
                "kind": "rental",
                "valuation_source": "appraisal",
                "purchase_price": 285_000_00,
                "purchase_date": "2016-08-01",
                "valuation_as_of": "2026-08-01",
            }
        )

        assert fields["kind"].value == "rental"
        assert fields["source"].value == "appraisal"
        assert fields["purchase_price"].value == "285000.00"
        assert fields["purchase_date"].value == "2016-08-01"
        assert fields["valued_on"].value == "2026-08-01"


class TestValuationHistoryMenu:
    def test_a_property_offers_valuation_history(self) -> None:
        labels = manage_menu_labels({"account_type": "property", "is_manual": True})

        assert "Valuation history" in labels

    def test_a_cash_account_does_not(self) -> None:
        labels = manage_menu_labels({"account_type": "checking", "is_manual": True})

        assert "Valuation history" not in labels


class TestValuationPayload:
    def test_payload_carries_the_text_and_its_source(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
            valuation_payload,
        )

        payload = valuation_payload(
            text="Aug 2026\t$711.2K", source="zillow", note="Zestimate history"
        )

        assert payload["text"].startswith("Aug 2026")
        assert payload["source"] == "zillow"
        assert payload["note"] == "Zestimate history"
        # A site's estimate is an estimate, and the label has to say so -
        # the model quotes whatever provenance it is handed.
        assert payload["is_estimate"] is True

    def test_a_typed_figure_is_not_an_estimate(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
            valuation_payload,
        )

        assert valuation_payload(text="2026-08-01,715000", source="manual")[
            "is_estimate"
        ] is False

    def test_an_empty_paste_is_rejected_before_the_request(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
            valuation_payload,
        )

        with pytest.raises(ValueError):
            valuation_payload(text="   \n ", source="zillow")


class TestPayload:
    def test_payload_carries_cents_and_iso_dates(self) -> None:
        payload = property_payload(
            purchase_price="285000",
            purchase_date=date(2016, 8, 1),
            down_payment="57000",
            property_kind="primary",
            valuation_source="user",
            valuation_as_of=date(2026, 8, 1),
            include_in_net_worth=True,
            address_label="House Bedner",
        )

        assert payload["purchase_price"] == 285_000_00
        assert payload["down_payment"] == 57_000_00
        assert payload["purchase_date"] == "2016-08-01"
        assert payload["valuation_as_of"] == "2026-08-01"
        assert payload["address_label"] == "House Bedner"

    def test_blank_money_fields_are_omitted_not_zeroed(self) -> None:
        """A blank purchase price means unknown. Sending 0 would claim the
        house was free and every equity figure downstream would inherit it."""
        payload = property_payload(purchase_price="", down_payment="  ")

        assert payload["purchase_price"] is None
        assert payload["down_payment"] is None

    def test_a_non_numeric_amount_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            property_payload(purchase_price="about three hundred grand")
