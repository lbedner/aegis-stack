"""How a script is written in the sandbox (``code_mode.SANDBOX_RULES``):
part of an agent's prompt exactly while code mode is on, whatever its
persona, and once."""

from app.services.ai.domains.chat.code_mode import SANDBOX_RULES, with_sandbox_rules

PERSONA = "I'm Illiana."


def test_the_rules_ride_code_mode() -> None:
    assert with_sandbox_rules(PERSONA, code_mode=False) == PERSONA
    ruled = with_sandbox_rules(PERSONA, code_mode=True)
    assert ruled.startswith(PERSONA) and ruled.endswith(SANDBOX_RULES)


def test_a_persona_that_carries_them_already_carries_them_once() -> None:
    """A row seeded when the rules lived in its persona (the finance
    assistant's) is not told twice."""
    stored = with_sandbox_rules(PERSONA, code_mode=True)
    assert with_sandbox_rules(stored, code_mode=True) == stored
