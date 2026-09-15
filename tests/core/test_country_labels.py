"""A country outside the hand-written list still gets its flag (#1096).

``COUNTRY_NAMES`` is 55 familiar spellings out of ~249 ISO codes, and every
consumer looked up with ``.get(code, code)``: an unmapped country rendered
as a bare code, flagless, and doubled in any view that printed the code
beside it. The flag is arithmetic on the code, so it was never the missing
half - only the name is.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _constants() -> dict[str, Any]:
    """The rendered ``app/core/constants.py``, executed in isolation."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    source = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/core/constants.py"
    ).render({**get_copier_defaults(), "project_slug": "demo"})
    start = source.index("def country_flag(")
    end = source.index("\n", source.index("COUNTRY_NAMES: dict"))
    namespace: dict[str, Any] = {}
    exec(source[start:end] + source[end:].split("\n)")[0] + "\n)", namespace)  # noqa: S102
    return namespace


def test_a_named_country_reads_as_flag_and_name() -> None:
    gen = _constants()

    assert gen["country_label"]("US") == "\U0001f1fa\U0001f1f8 United States"


def test_an_unnamed_country_keeps_its_flag() -> None:
    """Kyrgyzstan is one of the ~194 codes the list never had."""
    gen = _constants()

    label = gen["country_label"]("KG")

    assert label.startswith("\U0001f1f0\U0001f1ec")
    assert label.endswith("KG")


def test_a_code_that_is_not_a_country_gets_no_garbage_flag() -> None:
    gen = _constants()

    assert gen["country_flag"]("ZZZ") == ""
    assert gen["country_flag"]("") == ""
    assert gen["country_label"]("") == ""


def test_the_name_is_stored_without_its_flag() -> None:
    """Parts are separable, so a caller can render them independently."""
    gen = _constants()

    flag, name = gen["country_parts"]("de")

    assert flag == "\U0001f1e9\U0001f1ea"
    assert name == "Germany"
