"""Run a script in node, for the tests of the app's own JS (``static/js``).

One home for finding node, skipping where it is missing, and reading back
what the script printed; each test keeps only its harness.
"""

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest


def run(script: str, **modules: Path) -> Any:
    """What ``script`` printed, read as JSON. Each ``NAME=path`` replaces
    ``NAME`` in the script with that module's path, for ``require``."""
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node not installed")
    for name, path in modules.items():
        script = script.replace(name, json.dumps(str(path.resolve())))
    done = subprocess.run([exe, "-e", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def call(module: Path, expression: str) -> Any:
    """``expression`` evaluated with ``module`` required as ``c``."""
    return run(
        f"const c = require(MODULE); console.log(JSON.stringify({expression}));",
        MODULE=module,
    )
