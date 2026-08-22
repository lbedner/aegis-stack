"""Regression tests for AI provider resolution.

A bad ``AI_PROVIDER`` in ``.env`` (e.g. a vendor display name like ``llm7.io``
written by model auto-detect) must never crash-loop the webserver, and the
resolver must map known display names to the right provider. Guards against
the boot-bricking ``ValueError: 'llm7.io' is not a valid AIProvider``.
"""

from types import SimpleNamespace

import pytest

from app.services.ai.config import AIServiceConfig, _resolve_effort, _resolve_provider
from app.services.ai.models import AIProvider
from app.services.ai.domains.llm.providers import _model_settings, _supports_custom_temperature


class TestCustomTemperatureSupport:
    """gpt-5 family and o-series reasoning models reject any temperature but
    the default (1); sending one 400s. Those must omit temperature."""

    def test_fixed_temperature_models(self) -> None:
        for model in ["gpt-5.5", "gpt-5", "openai/gpt-5.2", "o1-mini", "o3", "o4-mini"]:
            assert _supports_custom_temperature(model) is False, model

    def test_custom_temperature_models(self) -> None:
        for model in ["gpt-4o", "gpt-4o-mini", "claude-sonnet-4-6", "auto", None]:
            assert _supports_custom_temperature(model) is True, model

    def test_model_settings_omits_temperature_for_fixed(self) -> None:
        cfg = SimpleNamespace(
            model="gpt-5.5", temperature=0.7, max_tokens=4096, timeout_seconds=120.0
        )
        assert "temperature" not in _model_settings(cfg)

    def test_model_settings_keeps_temperature_otherwise(self) -> None:
        cfg = SimpleNamespace(
            model="gpt-4o", temperature=0.7, max_tokens=4096, timeout_seconds=120.0
        )
        assert _model_settings(cfg)["temperature"] == 0.7


class TestAIProviderFromName:
    def test_canonical_value(self) -> None:
        assert AIProvider.from_name("public") is AIProvider.PUBLIC
        assert AIProvider.from_name("openai") is AIProvider.OPENAI

    def test_case_insensitive(self) -> None:
        assert AIProvider.from_name("OpenAI") is AIProvider.OPENAI
        assert AIProvider.from_name(" ANTHROPIC ") is AIProvider.ANTHROPIC

    def test_vendor_display_alias_maps_to_provider(self) -> None:
        # "LLM7.io" is the public provider's display name, not an enum value.
        assert AIProvider.from_name("LLM7.io") is AIProvider.PUBLIC
        assert AIProvider.from_name("llm7.io") is AIProvider.PUBLIC

    def test_unknown_returns_none(self) -> None:
        assert AIProvider.from_name("bogus") is None
        assert AIProvider.from_name("") is None
        assert AIProvider.from_name(None) is None


class TestResolveProviderNeverCrashes:
    def test_vendor_display_name_falls_back_cleanly(self) -> None:
        # The exact value that bricked boot must now resolve, not raise.
        assert _resolve_provider("llm7.io") is AIProvider.PUBLIC

    def test_unknown_value_falls_back_to_public(self) -> None:
        assert _resolve_provider("totally-bogus") is AIProvider.PUBLIC

    def test_valid_value_preserved(self) -> None:
        assert _resolve_provider("anthropic") is AIProvider.ANTHROPIC

    def test_from_settings_survives_bad_provider(self) -> None:
        settings = SimpleNamespace(AI_PROVIDER="llm7.io")
        config = AIServiceConfig.from_settings(settings)
        assert config.provider is AIProvider.PUBLIC


class TestResolveEffort:
    def test_valid_levels_normalized(self) -> None:
        assert _resolve_effort("LOW") == "low"
        assert _resolve_effort(" high ") == "high"

    def test_none_and_blank_pass_through(self) -> None:
        assert _resolve_effort(None) is None
        assert _resolve_effort("") is None

    def test_unknown_falls_back_to_none(self) -> None:
        assert _resolve_effort("turbo") is None  # warn-don't-crash


class TestEffortSetting:
    """AI_EFFORT flows to Anthropic as ``anthropic_effort``; other providers
    never see the key (their APIs would reject it)."""

    def _cfg(self, **overrides: object) -> SimpleNamespace:
        base: dict[str, object] = {
            "model": "claude-sonnet-5",
            "provider": AIProvider.ANTHROPIC,
            "temperature": 0.7,
            "effort": "low",
            "max_tokens": 4096,
            "timeout_seconds": 120.0,
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_effort_passed_for_anthropic(self) -> None:
        # Only meaningful when the anthropic extra is installed (the effort
        # branch builds AnthropicModelSettings, which needs the anthropic SDK).
        pytest.importorskip("anthropic")
        # ``_model_settings`` is annotated ``-> ModelSettings``; the effort
        # branch returns the ``AnthropicModelSettings`` subtype whose extra
        # ``anthropic_effort`` key the base TypedDict doesn't declare. Read it
        # through a plain dict so the type checker doesn't reject the key.
        settings = dict(_model_settings(self._cfg()))
        assert settings["anthropic_effort"] == "low"

    def test_effort_omitted_when_unset(self) -> None:
        assert "anthropic_effort" not in _model_settings(self._cfg(effort=None))

    def test_effort_omitted_for_other_providers(self) -> None:
        settings = _model_settings(
            self._cfg(model="gpt-4o", provider=AIProvider.OPENAI)
        )
        assert "anthropic_effort" not in settings
