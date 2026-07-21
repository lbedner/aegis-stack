"""Tests for system prompt assembly (persona override)."""

from unittest.mock import MagicMock

from app.services.ai.prompts import build_system_prompt


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.AI_ENABLED = True
    settings.PROJECT_NAME = "testproj"
    return settings


class TestPersonaOverride:
    def test_default_prompt_uses_builtin_persona(self) -> None:
        prompt = build_system_prompt(_settings())

        assert prompt.startswith("I'm Illiana.")

    def test_persona_replaces_builtin_block(self) -> None:
        prompt = build_system_prompt(_settings(), persona="You are Custom.")

        assert prompt.startswith("You are Custom.")
        assert "I'm Illiana" not in prompt

    def test_persona_keeps_dynamic_context_sections(self) -> None:
        """A custom persona still gets the live-data sections appended."""
        prompt = build_system_prompt(
            _settings(),
            persona="You are Custom.",
            health_context="ALL COMPONENTS HEALTHY",
            usage_context="42 requests today",
        )

        assert prompt.startswith("You are Custom.")
        assert "## System Status" in prompt
        assert "ALL COMPONENTS HEALTHY" in prompt
        assert "## My Activity" in prompt


class TestMemoryContext:
    def test_memory_context_section_is_appended(self) -> None:
        prompt = build_system_prompt(
            _settings(),
            memory_context="<user_memory>\n- [food] vegan\n</user_memory>",
        )

        assert "## Saved User Memory" in prompt
        assert "<user_memory>" in prompt
        assert "- [food] vegan" in prompt

    def test_no_memory_context_no_section(self) -> None:
        prompt = build_system_prompt(_settings())

        assert "## Saved User Memory" not in prompt
