"""Tests for the payee name a group SUGGESTS.

``normalize_payee`` deliberately destroys punctuation and case - it is a
dedup key, and "the goal is a key, not a pretty display name". Building
the suggested display name out of that key inherits the damage:
"McDonald's" normalizes to "MCDONALD S" and title-cases back to
"Mcdonald S", which is then what gets saved as the payee. Confirmed live
on two payees, "Mcdonald S" (368 transactions) and "Wendy S" (183).

The sample descriptor still has the original spelling, so the fix is to
prefer it when it is already a human-written name rather than a bank's
all-caps blob.
"""

from app.services.finance.utils import suggested_payee_name


class TestSuggestedPayeeName:
    def test_a_clean_sample_keeps_its_apostrophe(self) -> None:
        assert suggested_payee_name("MCDONALD S", "McDonald's") == "McDonald's"
        assert suggested_payee_name("WENDY S", "Wendy's") == "Wendy's"

    def test_a_clean_sample_keeps_its_interior_capitals(self) -> None:
        """``str.capitalize`` would flatten these to "Shoprite"/"Iheartmedia"."""
        assert suggested_payee_name("SHOPRITE", "ShopRite") == "ShopRite"
        assert suggested_payee_name("IHEARTMEDIA", "iHeartMedia") == "iHeartMedia"

    def test_a_shouty_bank_descriptor_falls_back_to_the_key(self) -> None:
        """An all-caps sample carries no case information worth keeping,
        and usually trails a store number and a city."""
        assert suggested_payee_name("TARGET", "TARGET POUGHKEEPSIE NY") == "Target"

    def test_a_noisy_descriptor_falls_back_to_the_key(self) -> None:
        """Mixed case is not enough on its own - this one has it, and is
        still not a name anybody would choose."""
        sample = "DOORDASH*CROWN FRIEDSAN FRANCIS NT_KBVL6WXU +16506819470"
        assert suggested_payee_name("DOORDASH CROWN FRIEDSAN FRANCIS", sample) == (
            "Doordash Crown Friedsan Francis"
        )

    def test_a_sample_with_a_card_or_store_number_is_rejected(self) -> None:
        assert suggested_payee_name("SQ JOES", "Sq *Joes 0093") == "Sq Joes"

    def test_no_sample_still_yields_the_key(self) -> None:
        assert suggested_payee_name("TARGET", None) == "Target"
        assert suggested_payee_name("TARGET", "") == "Target"

    def test_an_empty_key_is_empty(self) -> None:
        assert suggested_payee_name("", "") == ""
