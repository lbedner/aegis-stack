"""The plugin package prefix lives in exactly one place.

``aegis-stack-<name>`` is the distribution, ``aegis_stack_<name>`` the
import package. Every surface that builds one of those (scaffold output
dir, scaffold placeholders, install hints in ``aegis add`` and the
resolver, the ``plugins update`` locale string) goes through
``aegis.core.plugins.naming``; a literal prefix anywhere else is drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from aegis.core.plugins.naming import (
    DIST_PREFIX,
    PACKAGE_PREFIX,
    dist_name,
    package_name,
)

AEGIS = Path(__file__).resolve().parents[2] / "aegis"


def test_names_from_one_prefix() -> None:
    assert DIST_PREFIX == "aegis-stack-"
    assert PACKAGE_PREFIX == "aegis_stack_"
    assert dist_name("crawl4ai") == "aegis-stack-crawl4ai"
    assert package_name("crawl4ai") == "aegis_stack_crawl4ai"
    assert package_name("metrics_hub") == "aegis_stack_metrics_hub"


def test_no_literal_prefix_outside_naming_module() -> None:
    """Code that BUILDS a name must call the helpers: no f-string,
    concatenation, or ``.format`` spelling the prefix, and no scaffold
    template spelling it next to a Jinja variable (``{{ dist }}`` and
    ``{{ pkg }}`` come from the render context). Prose examples in
    docstrings, which name a whole package, are not matched."""
    offenders: list[str] = []
    code = re.compile(r"""["']aegis[-_]stack[-_]["'{]""")
    template = re.compile(r"aegis[-_]stack[-_]\{\{")
    for path in AEGIS.rglob("*"):
        if path.is_dir() or path.name == "naming.py":
            continue
        if path.suffix == ".jinja":
            pattern = template
        elif path.suffix == ".py":
            pattern = code
        else:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(AEGIS)}:{lineno}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
