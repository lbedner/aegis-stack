"""Every module under ``app/`` imports in this stack: a module that serves a
feature the stack lacks does not ship with it, so nothing that later imports
it breaks at runtime."""

from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# The migration tools ship with any database, alembic only where something
# migrates: until they leave with ``alembic/``, a stack without it skips them.
SKIPPED = () if find_spec("alembic") else ("app.cli.migrate_",)
# In its own process, so importing everything leaves this one as it was.
SWEEP = """
import importlib, sys
failed = []
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except Exception as error:
        failed.append(f"{name}: {type(error).__name__}: {error}")
if failed:
    raise SystemExit("\\n".join(failed))
"""


def _modules() -> list[str]:
    names = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        parts = path.relative_to(ROOT).with_suffix("").parts
        names.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return [name for name in names if not name.startswith(SKIPPED)]


def test_every_module_imports() -> None:
    result = subprocess.run(
        [sys.executable, "-c", SWEEP, *_modules()],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
