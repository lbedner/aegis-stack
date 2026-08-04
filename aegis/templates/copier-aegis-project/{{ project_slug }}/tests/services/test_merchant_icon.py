"""Tests for the payee icon domain guess.

Only the pure part is covered here: ``icons_for_names`` does network I/O
against a third-party favicon service, and a test that depends on that
would be testing Google's uptime, not this code.
"""

from app.services.finance.merchant_icon import merchant_icon_domain


class TestMerchantIconDomain:
    def test_clean_name_guesses_a_plausible_domain(self) -> None:
        assert merchant_icon_domain("Netflix") == "netflix.com"

    def test_punctuation_and_spacing_collapse_out(self) -> None:
        assert merchant_icon_domain("AT&T") == "att.com"

    def test_multi_word_name_joins_with_no_separator(self) -> None:
        assert merchant_icon_domain("State Farm") == "statefarm.com"

    def test_empty_input_has_nothing_to_guess_from(self) -> None:
        assert merchant_icon_domain("") is None
        assert merchant_icon_domain(None) is None

    def test_single_character_is_too_short_to_guess(self) -> None:
        assert merchant_icon_domain("$") is None

    def test_a_bank_descriptor_is_too_long_to_be_a_brand(self) -> None:
        """A finance-charge line is not a merchant, and guessing a domain
        from it can only ever miss - so it never costs a fetch."""
        assert merchant_icon_domain("INTEREST CHARGED TO PUR PR-11/28/25.") is None
