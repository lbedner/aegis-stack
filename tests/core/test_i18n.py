"""
Tests for i18n locale normalization and message completeness.

Verifies that locale detection, normalization, and message catalogs
work correctly across all supported languages.
"""

import pytest

from aegis.core.components import COMPONENTS
from aegis.core.plugins.spec import PluginSpec
from aegis.core.services import SERVICES
from aegis.i18n.locales import AVAILABLE_LOCALES
from aegis.i18n.locales.en import MESSAGES as EN_MESSAGES
from aegis.i18n.registry import _normalize_locale


class TestLocaleNormalization:
    """Test locale string normalization."""

    def test_english_variants(self) -> None:
        """English locale variants all normalize to 'en'."""
        assert _normalize_locale("en") == "en"
        assert _normalize_locale("en_US") == "en"
        assert _normalize_locale("en-GB") == "en"
        assert _normalize_locale("en_US.UTF-8") == "en"
        assert _normalize_locale("en.UTF-8") == "en"

    def test_simplified_chinese_variants(self) -> None:
        """Simplified Chinese variants all normalize to 'zh'."""
        assert _normalize_locale("zh") == "zh"
        assert _normalize_locale("zh_CN") == "zh"
        assert _normalize_locale("zh-Hans") == "zh"
        assert _normalize_locale("zh_CN.UTF-8") == "zh"

    def test_traditional_chinese_variants(self) -> None:
        """Traditional Chinese variants all normalize to 'zh_Hant'."""
        assert _normalize_locale("zh_TW") == "zh_Hant"
        assert _normalize_locale("zh_HK") == "zh_Hant"
        assert _normalize_locale("zh-Hant") == "zh_Hant"
        assert _normalize_locale("zh_MO") == "zh_Hant"
        assert _normalize_locale("zh_TW.UTF-8") == "zh_Hant"
        assert _normalize_locale("zh_HK.UTF-8") == "zh_Hant"

    def test_japanese_variants(self) -> None:
        """Japanese locale variants normalize to 'ja'."""
        assert _normalize_locale("ja") == "ja"
        assert _normalize_locale("ja_JP") == "ja"
        assert _normalize_locale("ja_JP.UTF-8") == "ja"
        assert _normalize_locale("ja-JP") == "ja"

    def test_korean_variants(self) -> None:
        """Korean locale variants normalize to 'ko'."""
        assert _normalize_locale("ko") == "ko"
        assert _normalize_locale("ko_KR") == "ko"
        assert _normalize_locale("ko_KR.UTF-8") == "ko"
        assert _normalize_locale("ko-KR") == "ko"

    def test_spanish_variants(self) -> None:
        """Spanish locale variants normalize to 'es'."""
        assert _normalize_locale("es") == "es"
        assert _normalize_locale("es_ES") == "es"
        assert _normalize_locale("es-MX") == "es"
        assert _normalize_locale("es_AR") == "es"
        assert _normalize_locale("es_ES.UTF-8") == "es"

    def test_german_variants(self) -> None:
        """German locale variants normalize to 'de'."""
        assert _normalize_locale("de") == "de"
        assert _normalize_locale("de_DE") == "de"
        assert _normalize_locale("de-DE") == "de"
        assert _normalize_locale("de_AT") == "de"
        assert _normalize_locale("de_CH") == "de"
        assert _normalize_locale("de_DE.UTF-8") == "de"

    def test_russian_variants(self) -> None:
        """Russian locale variants normalize to 'ru'."""
        assert _normalize_locale("ru") == "ru"
        assert _normalize_locale("ru_RU") == "ru"
        assert _normalize_locale("ru-RU") == "ru"
        assert _normalize_locale("ru_RU.UTF-8") == "ru"

    def test_unsupported_falls_back_to_english(self) -> None:
        """Unsupported locales fall back to 'en'."""
        assert _normalize_locale("xx") == "en"
        assert _normalize_locale("pt_BR") == "en"
        assert _normalize_locale("sv_SE") == "en"

    def test_encoding_and_modifier_stripped(self) -> None:
        """Encoding suffixes and modifiers are stripped."""
        assert _normalize_locale("ja_JP.EUC-JP") == "ja"
        assert _normalize_locale("zh_TW.Big5") == "zh_Hant"
        assert _normalize_locale("en_US.UTF-8@euro") == "en"
        assert _normalize_locale("de_DE.UTF-8@euro") == "de"
        assert _normalize_locale("ru_RU.KOI8-R") == "ru"

    def test_french_variants(self) -> None:
        """French locale variants normalize to 'fr'."""
        assert _normalize_locale("fr") == "fr"
        assert _normalize_locale("fr_FR") == "fr"
        assert _normalize_locale("fr-FR") == "fr"
        assert _normalize_locale("fr_FR.UTF-8") == "fr"
        assert _normalize_locale("fr_CA") == "fr"


class TestMessageCompleteness:
    """Test that all locale catalogs have the same keys as English."""

    def test_all_locales_registered(self) -> None:
        """All expected locales are in AVAILABLE_LOCALES."""
        assert "de" in AVAILABLE_LOCALES
        assert "en" in AVAILABLE_LOCALES
        assert "es" in AVAILABLE_LOCALES
        assert "fr" in AVAILABLE_LOCALES
        assert "ja" in AVAILABLE_LOCALES
        assert "ko" in AVAILABLE_LOCALES
        assert "ru" in AVAILABLE_LOCALES
        assert "zh" in AVAILABLE_LOCALES
        assert "zh_Hant" in AVAILABLE_LOCALES

    def test_es_has_all_keys(self) -> None:
        """Spanish has all English keys."""
        from aegis.i18n.locales.es import MESSAGES as ES

        missing = set(EN_MESSAGES) - set(ES)
        extra = set(ES) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not es: {missing}"
        assert not extra, f"Keys in es but not en: {extra}"

    def test_de_has_all_keys(self) -> None:
        """German has all English keys."""
        from aegis.i18n.locales.de import MESSAGES as DE

        missing = set(EN_MESSAGES) - set(DE)
        extra = set(DE) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not de: {missing}"
        assert not extra, f"Keys in de but not en: {extra}"

    def test_ru_has_all_keys(self) -> None:
        """Russian has all English keys."""
        from aegis.i18n.locales.ru import MESSAGES as RU

        missing = set(EN_MESSAGES) - set(RU)
        extra = set(RU) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not ru: {missing}"
        assert not extra, f"Keys in ru but not en: {extra}"

    def test_fr_has_all_keys(self) -> None:
        """French has all English keys."""
        from aegis.i18n.locales.fr import MESSAGES as FR

        missing = set(EN_MESSAGES) - set(FR)
        extra = set(FR) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not fr: {missing}"
        assert not extra, f"Keys in fr but not en: {extra}"

    def test_zh_has_all_keys(self) -> None:
        """Simplified Chinese has all English keys."""
        from aegis.i18n.locales.zh import MESSAGES as ZH

        missing = set(EN_MESSAGES) - set(ZH)
        extra = set(ZH) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not zh: {missing}"
        assert not extra, f"Keys in zh but not en: {extra}"

    def test_zh_hant_has_all_keys(self) -> None:
        """Traditional Chinese has all English keys."""
        from aegis.i18n.locales.zh_hant import MESSAGES as ZH_HANT

        missing = set(EN_MESSAGES) - set(ZH_HANT)
        extra = set(ZH_HANT) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not zh_Hant: {missing}"
        assert not extra, f"Keys in zh_Hant but not en: {extra}"

    def test_ja_has_all_keys(self) -> None:
        """Japanese has all English keys."""
        from aegis.i18n.locales.ja import MESSAGES as JA

        missing = set(EN_MESSAGES) - set(JA)
        extra = set(JA) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not ja: {missing}"
        assert not extra, f"Keys in ja but not en: {extra}"

    def test_ko_has_all_keys(self) -> None:
        """Korean has all English keys."""
        from aegis.i18n.locales.ko import MESSAGES as KO

        missing = set(EN_MESSAGES) - set(KO)
        extra = set(KO) - set(EN_MESSAGES)
        assert not missing, f"Keys in en but not ko: {missing}"
        assert not extra, f"Keys in ko but not en: {extra}"

    def test_no_empty_values(self) -> None:
        """No locale has empty string values."""
        from aegis.i18n.locales.de import MESSAGES as DE
        from aegis.i18n.locales.es import MESSAGES as ES
        from aegis.i18n.locales.fr import MESSAGES as FR
        from aegis.i18n.locales.ja import MESSAGES as JA
        from aegis.i18n.locales.ko import MESSAGES as KO
        from aegis.i18n.locales.ru import MESSAGES as RU
        from aegis.i18n.locales.zh import MESSAGES as ZH
        from aegis.i18n.locales.zh_hant import MESSAGES as ZH_HANT

        for name, messages in [
            ("de", DE),
            ("es", ES),
            ("fr", FR),
            ("ja", JA),
            ("ko", KO),
            ("ru", RU),
            ("zh", ZH),
            ("zh_Hant", ZH_HANT),
        ]:
            empty = [k for k, v in messages.items() if not v.strip()]
            assert not empty, f"{name} has empty values: {empty}"


@pytest.mark.parametrize(
    ("key", "spec"),
    [(f"component.{n}", s) for n, s in COMPONENTS.items()]
    + [(f"service.{n}", s) for n, s in SERVICES.items()],
)
def test_spec_description_matches_locale(key: str, spec: PluginSpec) -> None:
    """Every registered spec's one-liner is a locale key with the same text.

    Prompts read the locale; the spec is only the fallback, so the two
    drifting means some flows show different copy than others.
    """
    assert EN_MESSAGES.get(key) == spec.description
