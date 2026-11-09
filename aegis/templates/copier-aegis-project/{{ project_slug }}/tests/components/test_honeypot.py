"""The honeypot every public form shares: one field, one check."""

from typing import Any

import pytest

from app.components.backend.security import honeypot


@pytest.mark.parametrize(
    ("fields", "filled"),
    [
        ({"email": "ada@example.com"}, False),
        ({"email": "ada@example.com", honeypot.FIELD: ""}, False),
        ({"email": "ada@example.com", honeypot.FIELD: "  "}, False),
        ({"email": "bot@example.com", honeypot.FIELD: "https://spam.example"}, True),
    ],
)
def test_only_a_filled_trap_trips(fields: dict[str, Any], filled: bool) -> None:
    assert honeypot.tripped(fields, form="register") is filled
