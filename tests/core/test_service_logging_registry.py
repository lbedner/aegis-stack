"""Runtime service constants track the generator's service specifications."""

import ast
from pathlib import Path

from aegis.core.services import SERVICES


def test_runtime_service_names_match_specs() -> None:
    path = (
        Path(__file__).parents[2]
        / "aegis/templates/copier-aegis-project/{{ project_slug }}/app/core/constants.py"
    )
    tree = ast.parse(path.read_text())
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ServiceName"
    ]
    assert classes, "ServiceName runtime registry is missing"
    values = {
        ast.literal_eval(node.value)
        for node in classes[0].body
        if isinstance(node, ast.Assign)
    }
    assert values == set(SERVICES)
