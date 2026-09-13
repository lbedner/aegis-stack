"""``alembic/env.py`` must not pass an option both literally and by splat.

``app/cli/migrate_gen.py`` hands ``include_object``, ``compare_type`` and
friends to ``env.py`` through ``config.attributes["configure"]``. While
``env.py`` splats those on top of literal keyword arguments, a project that
adds a default of its own to the same call gets ``TypeError: configure() got
multiple values for keyword argument``. Route every option through one dict
and the collision cannot be written.
"""

import ast
import re
from pathlib import Path

from aegis.core.component_files import get_template_path

ENV_PY = Path(get_template_path()) / "{{ project_slug }}" / "alembic" / "env.py.jinja"
JINJA_TAG = re.compile(r"^\s*\{%.*%\}\s*$\n?", re.M)


def _configure_calls() -> list[ast.Call]:
    source = JINJA_TAG.sub("", ENV_PY.read_text())
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "configure"
    ]


def test_online_configure_takes_options_only_by_splat() -> None:
    """The call that receives caller options carries no colliding literal."""
    splatting = [
        call
        for call in _configure_calls()
        if any(kw.arg is None for kw in call.keywords)
    ]
    assert splatting, "env.py no longer forwards config.attributes['configure']"
    for call in splatting:
        literals = [
            kw.arg for kw in call.keywords if kw.arg not in (None, "connection")
        ]
        assert not literals, (
            "context.configure() mixes literal options with the caller splat, "
            f"so a project default for any of {literals} raises TypeError"
        )
