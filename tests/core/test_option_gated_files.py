"""An option that is off ships none of its files, whichever path adds them.

``init`` removes an option's files in ``post_gen_tasks.cleanup_components``;
``aegis add`` / ``add-service`` copy what the spec's ``FileManifest`` says.
The two drifted: RAG's chat context modules and voice's speech router were
removed by init but sat in the always-copied ``app/services/ai`` tree, and a
gated group inside a spec's own primary directory was never subtracted, so
adding ``ai`` without voice copied the whole voice package.
"""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pytest

from aegis.constants import AnswerKeys
from aegis.core import post_gen_tasks
from aegis.core.component_files import (
    SCHEDULER_PERSISTENCE,
    _expand_directories_to_files,
    get_all_owned_paths,
    get_component_files,
    get_copier_defaults,
)
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES

SPECS = {**SERVICES, **COMPONENTS}


def _answer_groups() -> list[tuple[str, str]]:
    """(spec, extras group) pairs whose group is an answer, i.e. a gate."""
    return [
        (name, group)
        for name, spec in SPECS.items()
        for group in (spec.files.extras or {})
        if group != SCHEDULER_PERSISTENCE
    ]


def _init_removals() -> dict[str, set[str]]:
    """Paths ``cleanup_components`` removes under ``if not is_enabled(X)``,
    keyed by X's answer name."""
    tree = ast.parse(inspect.getsource(post_gen_tasks.cleanup_components))
    removals: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # ``not is_enabled(X)``, alone or as one operand of an ``and``.
        tests = node.test.values if isinstance(node.test, ast.BoolOp) else [node.test]
        negated = [
            t.operand.args[0]
            for t in tests
            if isinstance(t, ast.UnaryOp)
            and isinstance(t.op, ast.Not)
            and isinstance(t.operand, ast.Call)
            and getattr(t.operand.func, "id", None) == "is_enabled"
            and isinstance(t.operand.args[0], ast.Attribute)
        ]
        if len(negated) != 1:
            continue
        answer = getattr(AnswerKeys, negated[0].attr)
        for call in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if (
                isinstance(call, ast.Call)
                and getattr(call.func, "id", None) in ("remove_file", "remove_dir")
                and isinstance(call.args[1], ast.Constant)
            ):
                removals.setdefault(answer, set()).add(str(call.args[1].value))
    return removals


@pytest.mark.parametrize("answer", sorted(_init_removals()))
def test_what_init_removes_for_an_option_is_that_options_group(answer: str) -> None:
    declared: set[str] = set()
    for spec in SPECS.values():
        declared |= set(
            _expand_directories_to_files((spec.files.extras or {}).get(answer, []))
        )
    removed = set(_expand_directories_to_files(sorted(_init_removals()[answer])))
    # A file no spec owns is the shared-file engine's, which renders it per
    # answer; a spec's file has to be gated in its manifest.
    owned_ungated = (removed - declared) & get_all_owned_paths()
    assert not owned_ungated, (
        f"init removes these when {answer} is off, but their spec copies them "
        f"regardless: {sorted(owned_ungated)}"
    )


@pytest.mark.parametrize(("spec", "group"), _answer_groups())
def test_an_option_that_is_off_adds_none_of_its_files(spec: str, group: str) -> None:
    answers: dict[str, Any] = {
        **get_copier_defaults(),
        AnswerKeys.include_key(spec): True,
        group: False,
    }
    gated = set(_expand_directories_to_files(SPECS[spec].files.extras[group]))
    added = set(get_component_files(spec, answers=answers))
    assert not added & gated, sorted(added & gated)[:10]
