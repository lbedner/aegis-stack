"""A live call's rules (``call-state.js``) are plain JS, tested on Node's
own runner (``tests/js``) with nothing to install; this runs them with the
suite, so ``make check`` and CI hold them too."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_call_rules_hold() -> None:
    files = sorted(str(path) for path in (ROOT / "tests" / "js").glob("*.test.js"))
    assert files
    result = subprocess.run(
        ["node", "--test", *files], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_page_loads_the_rules_before_the_call() -> None:
    base = (ROOT / "app/components/web_frontend/templates/base.html").read_text()
    assert base.index("js/call-state.js") < base.index("js/voice.js")
    assert base.index("js/mentions.js") < base.index("js/voice.js")  # it follows her
