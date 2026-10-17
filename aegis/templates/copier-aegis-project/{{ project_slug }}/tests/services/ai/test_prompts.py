"""Tests for system prompt assembly (persona override)."""

from app.services.ai.domains.chat.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    build_system_prompt,
)


class TestPersonaOverride:
    def test_default_prompt_uses_builtin_persona(self) -> None:
        prompt = build_system_prompt()

        assert prompt.startswith("I'm Illiana.")

    def test_persona_replaces_builtin_block(self) -> None:
        prompt = build_system_prompt(persona="You are Custom.")

        assert prompt.startswith("You are Custom.")
        assert "I'm Illiana" not in prompt

    def test_persona_keeps_the_sections_after_it(self) -> None:
        """A custom persona still gets the sections appended after it."""
        prompt = build_system_prompt(
            persona="You are Custom.",
            memory_context="<user_memory>\n- [food] vegan\n</user_memory>",
        )

        assert prompt.startswith("You are Custom.")
        assert "- [food] vegan" in prompt


class TestThePersonaIsTheRow:
    """The seeded row holds the whole persona, editable like any other:
    it held a marker the code swapped for a built-in one, so the row said
    one thing and she ran on another (2026-10-16)."""

    def test_the_seeded_persona_is_the_prompt_she_runs_on(self) -> None:
        assert build_system_prompt() == build_system_prompt(
            persona=DEFAULT_SYSTEM_PROMPT
        )

    def test_an_edited_persona_still_knows_its_model(self) -> None:
        prompt = build_system_prompt(persona="You are Custom.", current_model="gpt-x")

        assert "gpt-x" in prompt


class TestMemoryContext:
    def test_memory_context_section_is_appended(self) -> None:
        prompt = build_system_prompt(
            memory_context="<user_memory>\n- [food] vegan\n</user_memory>",
        )

        assert "## Saved User Memory" in prompt
        assert "<user_memory>" in prompt
        assert "- [food] vegan" in prompt

    def test_no_memory_context_no_section(self) -> None:
        prompt = build_system_prompt()

        assert "## Saved User Memory" not in prompt
