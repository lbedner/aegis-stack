"""Structural invariants for the Copier template tree.

These are cheap whole-tree scans that catch a class of bug no per-file test
would: a file that looks authoritative but never reaches a generated
project.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

from aegis.core.component_files import get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
JINJA_SUFFIX = ".jinja"


def _project_tree() -> Path:
    return get_template_path() / PROJECT_SLUG_PLACEHOLDER


def _template_names() -> list[str]:
    root = get_template_path()
    return [str(p.relative_to(root)) for p in sorted(root.rglob(f"*{JINJA_SUFFIX}"))]


@pytest.mark.parametrize("name", _template_names())
def test_every_template_parses(name: str) -> None:
    """Every ``.jinja`` must be syntactically valid Jinja.

    Parsing is not rendering: this needs no context and no answers, so it
    catches a broken tag in any template, including ones no other test
    renders. Without it a syntax error only surfaces when someone generates
    a project, as ``Error creating project: tag name expected`` with no file
    named.

    The classic way in is a comment that talks about Jinja: ``{%`` inside a
    comment is still a tag to the parser.
    """
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    try:
        env.get_template(name)
    except TemplateSyntaxError as exc:
        pytest.fail(f"{name}:{exc.lineno}: {exc.message}")


def _module_to_path(module: str) -> str:
    return module.replace(".", "/")


def _covers(rel: str, owned: list[str]) -> bool:
    return any(
        rel == entry or rel.startswith(entry.rstrip("/") + "/") for entry in owned
    )


def test_a_plain_file_importing_a_service_module_is_owned_by_that_service() -> None:
    """A plain file whose top-level imports reach into a service must be
    listed in that service's file manifest.

    Service files are pruned from stacks that don't select the service. A
    plain ``.py`` cannot gate its imports the way a ``.jinja`` can, so if it
    imports a pruned module without itself being pruned, it ships everywhere
    and breaks collection on every stack without the service - which is
    exactly how the whole CI stack matrix goes red at once.
    """
    from aegis.core.services import SERVICES

    ownership: dict[str, list[str]] = {}
    for service_name, spec in SERVICES.items():
        entries = list(spec.template_files or [])
        if spec.files is not None:
            entries += list(spec.files.primary or [])
            # Option-gated groups (voice, rag, ...) render empty or vanish
            # with their option, so files in them are pruned too - they are
            # owned, just conditionally.
            for group in (spec.files.extras or {}).values():
                entries += list(group)
        ownership[service_name] = entries

    tree = _project_tree()
    violations: list[str] = []
    for path in sorted(tree.rglob("*.py")):
        rel = str(path.relative_to(tree))
        for line in path.read_text(errors="replace").splitlines():
            if not (line.startswith("from app.") or line.startswith("import app.")):
                continue
            module = line.split()[1]
            module_rel = _module_to_path(module)
            for service_name, owned in ownership.items():
                imported_is_owned = _covers(f"{module_rel}.py", owned) or _covers(
                    module_rel, owned
                )
                if imported_is_owned and not _covers(rel, owned):
                    violations.append(
                        f"{rel} imports {module} ({service_name}-owned) but is "
                        f"not in the {service_name} file manifest"
                    )
    assert not violations, (
        "These plain files ship to every stack but import service-pruned "
        "modules:\n  " + "\n  ".join(sorted(set(violations)))
    )


def test_no_file_is_shadowed_by_a_jinja_twin() -> None:
    """A file may ship as ``X`` or as ``X.jinja``, never both.

    Copier strips the ``.jinja`` suffix, so a pair renders to the same
    destination and one silently overwrites the other. Which one wins is
    decided by directory walk order, not by intent, and the loser looks
    like live source: editing it changes nothing in generated projects.
    """
    tree = _project_tree()
    shadowed = [
        str(path.relative_to(tree))
        for path in tree.rglob(f"*{JINJA_SUFFIX}")
        if path.with_suffix("").exists()
    ]
    assert not shadowed, (
        "These paths ship as both a plain file and a .jinja template; "
        "both render to the same destination and one silently wins:\n  "
        + "\n  ".join(shadowed)
    )
