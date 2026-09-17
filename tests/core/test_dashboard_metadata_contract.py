"""Every metadata key the dashboard reads is produced by something.

``ComponentStatus.metadata`` is ``dict[str, Any]``, and the dashboard
reads it exclusively through ``.get(key, default)``. That means a key
nobody produces does not raise, does not log, and does not fail a test:
it renders as ``0``, ``-`` or blank, which looks like a real reading.

A backend modal advertising "CPU Usage (0 cores)" on every machine is
what that looks like in practice - it read ``core_count`` while the
health check published ``cpu_count``, and the default made the mismatch
invisible for as long as nobody counted their own cores.

The producer and the consumer live in different files with only a string
between them, so this is the contract. It is a repo test rather than a
generated-project one because any single stack renders only a subset of
both sides.
"""

from __future__ import annotations

import re

import pytest

from aegis.core.component_files import get_template_path

TEMPLATE = get_template_path() / "{{ project_slug }}"
FRONTEND = TEMPLATE / "app" / "components" / "frontend"

READ = re.compile(r'metadata\.get\(\s*["\']([a-zA-Z_0-9]+)["\']')
# A producer writes the key as a dict key, a kwarg, or a subscript
# assignment. Jinja-rendered files count; their tags are stripped first.
WRITTEN = re.compile(
    r'["\']([a-zA-Z_0-9]+)["\']\s*:'  # {"key": value}
    r"|\b([a-zA-Z_0-9]+)\s*="  # key=value  /  key = value
    r'|\[\s*["\']([a-zA-Z_0-9]+)["\']\s*\]'  # d["key"] = value
)


def _source(path) -> str:
    text = path.read_text(errors="ignore")
    if path.suffix == ".jinja":
        text = re.sub(r"\{%.*?%\}", "", text, flags=re.S)
        text = re.sub(r"\{\{.*?\}\}", "X", text, flags=re.S)
    return text


def _python_files(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".jinja"):
            yield path


def keys_read() -> dict[str, set[str]]:
    """Metadata keys the dashboard reads, and where."""
    found: dict[str, set[str]] = {}
    for path in _python_files(FRONTEND):
        for match in READ.finditer(_source(path)):
            found.setdefault(match.group(1), set()).add(path.name)
    return found


def keys_produced() -> set[str]:
    """Every name written as a key or kwarg outside the frontend."""
    produced: set[str] = set()
    for path in _python_files(TEMPLATE / "app"):
        if FRONTEND in path.parents:
            continue
        for match in WRITTEN.finditer(_source(path)):
            produced.update(g for g in match.groups() if g)
    return produced


READS = keys_read()
PRODUCED = keys_produced()


def test_the_dashboard_reads_something() -> None:
    """Guard the guard: a regex that matches nothing would pass every
    assertion below."""
    assert len(READS) > 50, f"only found {len(READS)} metadata reads; regex drifted"


@pytest.mark.parametrize("key", sorted(READS))
def test_every_key_the_dashboard_reads_is_produced(key: str) -> None:
    assert key in PRODUCED, (
        f"'{key}' is read in {', '.join(sorted(READS[key]))} but nothing "
        f"outside the frontend ever writes it. The .get() default renders "
        f"instead, so the field shows a plausible value and says nothing."
    )
