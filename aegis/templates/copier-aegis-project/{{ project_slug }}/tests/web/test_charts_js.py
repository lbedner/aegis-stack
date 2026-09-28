"""How charts.js formats axis ticks and tooltips, run in node.

A chart's numbers are plain unless its data says ``"format": "money"``:
a generic macro must not read jobs per hour as dollars.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

CHARTS_JS = Path("app/components/web_frontend/static/js/charts.js")


def _format(value: float, fmt: str | None) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = (
        f"const c = require({json.dumps(str(CHARTS_JS.resolve()))});"
        f"console.log(JSON.stringify(c.formatValue({value}, {json.dumps(fmt)})));"
    )
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def test_numbers_are_plain_by_default() -> None:
    assert _format(250, None) == "250"
    assert "$" not in _format(1234.5, None)


def test_money_is_opt_in() -> None:
    assert _format(-1234.5, "money") == "-$1,234.50"
