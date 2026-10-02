"""Generated code imports on every Python a project may choose, 3.13 included.

Python 3.14 defers annotations; 3.13 evaluates a function's annotations when
the ``def`` runs. A name that does not exist yet at that moment raises
``NameError`` at import: ``AIServiceConfig.from_settings -> AIServiceConfig``
took down every 3.13 project with the AI service, unnoticed because new
projects, CI and the live app all run 3.14. ruff and ty pass these, so this
reads the source: in a template ``.py`` without ``from __future__ import
annotations``, no annotation may name

- the class it sits in (the class is bound only after its body runs),
- a module-level class or function defined further down the file, or
- a name imported only under ``if TYPE_CHECKING:``.

``typing.Self`` or a quoted name is the fix.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

TEMPLATE = get_template_path() / "{{ project_slug }}"


def _sources() -> Iterator[tuple[Path, str]]:
    """Every template module as Python source: ``.py`` as is, ``.py.jinja``
    rendered with every option on (the widest branch of each gate)."""
    for path in TEMPLATE.rglob("*.py"):
        yield path, path.read_text()
    defaults = get_copier_defaults()
    context = {
        **defaults,
        **{k: True for k, v in defaults.items() if k.startswith("include_")},
        "ai_rag": True,
        "ai_voice": True,
        "ai_backend": "sqlite",
        "scheduler_backend": "sqlite",
    }
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    for path in TEMPLATE.rglob("*.py.jinja"):
        name = path.relative_to(get_template_path()).as_posix()
        yield path, env.get_template(name).render(context)


def _has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _type_checking_only(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            for stmt in node.body:
                if isinstance(stmt, ast.Import | ast.ImportFrom):
                    names |= {(a.asname or a.name).split(".")[0] for a in stmt.names}
    return names


def _annotation_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[str]:
    args = func.args
    annotated = [
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *([args.vararg] if args.vararg else []),
        *([args.kwarg] if args.kwarg else []),
    ]
    for annotation in [a.annotation for a in annotated] + [func.returns]:
        if annotation is None:
            continue
        for node in ast.walk(annotation):
            if isinstance(node, ast.Name):
                yield node.id


def _problems(path: Path, source: str) -> Iterator[str]:
    tree = ast.parse(source)
    if _has_future_annotations(tree):
        return
    guarded = _type_checking_only(tree)
    defined_at = {
        node.name: node.lineno
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }

    def check(func: ast.FunctionDef | ast.AsyncFunctionDef, enclosing: str | None):
        for name in _annotation_names(func):
            where = f"{path.relative_to(TEMPLATE)}:{func.lineno} {func.name}"
            if name == enclosing:
                yield f"{where}: names its own class {name}"
            elif name in guarded:
                yield f"{where}: {name} is imported only under TYPE_CHECKING"
            elif defined_at.get(name, 0) > func.lineno:
                yield f"{where}: {name} is defined further down"

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield from check(item, node.name)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from check(node, None)


def test_no_annotation_names_what_313_has_not_bound_yet() -> None:
    found = sorted(
        {problem for path, source in _sources() for problem in _problems(path, source)}
    )
    assert not found, "NameError at import on Python 3.13:\n" + "\n".join(found)
