"""A question that nothing reads should not be asked.

``finance_import`` shipped with the finance service as a sub-flag, was
offered in the wizard, stored in every project's ``.copier-answers.yml``,
and read by nothing — no template file, no aegis code. Three template
versions of a promise that optionality existed when it never did, and the
answer-recovery guard had to carry a whole category to tolerate it.

A question is read when a template file references it (that is where a
Jinja variable is consumed) or when aegis code references its ``AnswerKeys``
constant. Comments do not count, which is why the code side matches the
constant rather than the lowercase value: ``services.py`` carried a comment
claiming ``finance_import`` gated ``pyproject.toml``, and it never did.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from aegis.constants import AnswerKeys

REPO = Path(__file__).parents[2]
TEMPLATE = REPO / "aegis" / "templates" / "copier-aegis-project"
AEGIS = REPO / "aegis"


def _questions() -> set[str]:
    loaded: dict[str, Any] = yaml.safe_load((REPO / "copier.yml").read_text()) or {}
    return {
        key
        for key, value in loaded.items()
        if not key.startswith("_") and isinstance(value, dict) and "type" in value
    }


def _answer_key_constants() -> dict[str, str]:
    """Answer value -> the ``AnswerKeys`` attribute that names it."""
    return {
        value: name
        for name, value in vars(AnswerKeys).items()
        if isinstance(value, str) and not name.startswith("_")
    }


def _read_by_templates(questions: set[str]) -> set[str]:
    """Whole-word: a table named ``finance_import_profile`` is not a read."""
    found: set[str] = set()
    for path in TEMPLATE.rglob("*"):
        # The answers file records every answer by definition — it would
        # report all of them as read and hide exactly this bug.
        if not path.is_file() or path.name == ".copier-answers.yml.jinja":
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        found |= {
            q for q in questions - found if re.search(rf"\b{re.escape(q)}\b", text)
        }
    return found


def _read_by_aegis(questions: set[str]) -> set[str]:
    constants = _answer_key_constants()
    found: set[str] = set()
    for path in AEGIS.rglob("*.py"):
        if "templates" in path.parts or path.name == "constants.py":
            continue
        text = path.read_text()
        found |= {
            q
            for q in questions - found
            if q in constants and re.search(rf"\b{constants[q]}\b", text)
        }
    return found


def test_every_question_is_read_by_something() -> None:
    questions = _questions()
    unread = sorted(
        questions - _read_by_templates(questions) - _read_by_aegis(questions)
    )
    assert not unread, (
        "These copier questions are asked, stored, and read by nothing — no "
        f"template file and no aegis code: {unread}.\n"
        "Either wire the answer up to what it was meant to gate, or delete "
        "the question so projects stop being asked about it."
    )
