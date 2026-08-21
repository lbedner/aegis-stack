"""Tests for AI provider to pydantic-ai-slim extra mapping."""

from unittest.mock import patch

from aegis.cli.interactive import clear_ai_provider_selection
from aegis.core.template_generator import TemplateGenerator


class TestPydanticAIProviderExtraMapping:
    """Test provider-to-extra mapping for pydantic-ai-slim dependencies."""

    def setup_method(self) -> None:
        """Clear provider selection before each test."""
        clear_ai_provider_selection()

    def test_public_provider_maps_to_openai_extra(self) -> None:
        """PUBLIC provider should map to openai extra since it uses OpenAI-compatible API."""
        with (
            patch(
                "aegis.cli.interactive.get_ai_provider_selection",
                return_value=["public"],
            ),
            patch(
                "aegis.cli.interactive.get_ai_framework_selection",
                return_value="pydantic-ai",
            ),
        ):
            generator = TemplateGenerator(
                project_name="test",
                selected_components=[],
                selected_services=["ai"],
            )
            deps = generator._get_ai_framework_deps()

            # Should have pydantic-ai-slim[openai], NOT pydantic-ai-slim[public]
            assert any("pydantic-ai-slim[openai]" in dep for dep in deps)
            assert not any("pydantic-ai-slim[public]" in dep for dep in deps)

    def test_pollinations_provider_maps_to_openai_extra(self) -> None:
        """Pollinations provider should map to openai extra (OpenAI-compatible API)."""
        with (
            patch(
                "aegis.cli.interactive.get_ai_provider_selection",
                return_value=["pollinations"],
            ),
            patch(
                "aegis.cli.interactive.get_ai_framework_selection",
                return_value="pydantic-ai",
            ),
        ):
            generator = TemplateGenerator(
                project_name="test",
                selected_components=[],
                selected_services=["ai"],
            )
            deps = generator._get_ai_framework_deps()

            assert any("pydantic-ai-slim[openai]" in dep for dep in deps)
            assert not any("pydantic-ai-slim[pollinations]" in dep for dep in deps)

    def test_openrouter_provider_maps_to_openai_extra(self) -> None:
        """OpenRouter provider should map to openai extra."""
        with (
            patch(
                "aegis.cli.interactive.get_ai_provider_selection",
                return_value=["openrouter"],
            ),
            patch(
                "aegis.cli.interactive.get_ai_framework_selection",
                return_value="pydantic-ai",
            ),
        ):
            generator = TemplateGenerator(
                project_name="test",
                selected_components=[],
                selected_services=["ai"],
            )
            deps = generator._get_ai_framework_deps()

            assert any("pydantic-ai-slim[openai]" in dep for dep in deps)
            assert not any("pydantic-ai-slim[openrouter]" in dep for dep in deps)

    def test_native_providers_pass_through(self) -> None:
        """Native providers (openai, anthropic, etc.) should pass through unchanged."""
        with (
            patch(
                "aegis.cli.interactive.get_ai_provider_selection",
                return_value=["openai", "anthropic", "google"],
            ),
            patch(
                "aegis.cli.interactive.get_ai_framework_selection",
                return_value="pydantic-ai",
            ),
        ):
            generator = TemplateGenerator(
                project_name="test",
                selected_components=[],
                selected_services=["ai"],
            )
            deps = generator._get_ai_framework_deps()

            # Should have all three extras
            pydantic_dep = next(d for d in deps if "pydantic-ai-slim" in d)
            assert "openai" in pydantic_dep
            assert "anthropic" in pydantic_dep
            assert "google" in pydantic_dep

    def test_mixed_providers_deduplicate(self) -> None:
        """public + openai should result in single openai extra, not duplicates."""
        with (
            patch(
                "aegis.cli.interactive.get_ai_provider_selection",
                return_value=["public", "openai"],
            ),
            patch(
                "aegis.cli.interactive.get_ai_framework_selection",
                return_value="pydantic-ai",
            ),
        ):
            generator = TemplateGenerator(
                project_name="test",
                selected_components=[],
                selected_services=["ai"],
            )
            deps = generator._get_ai_framework_deps()

            pydantic_dep = next(d for d in deps if "pydantic-ai-slim" in d)
            # Should only have "openai" once, not "openai,openai"
            assert pydantic_dep.count("openai") == 1
