"""Server setup adds swap on small boxes (aegis-stack#1559).

A 2 GB box builds the image on the server beside the running stack; with
no swap an OOM kill has nothing to fall back on. The step runs on every
``aegis deploy-setup`` and first boot, so it has to be idempotent.
"""

from __future__ import annotations

import subprocess

from tests.core.test_observability_oom_renders import _ctx, _render


def _script() -> str:
    return _render("scripts/server-setup.sh.jinja", _ctx(include_ingress=True))


def test_rendered_script_parses() -> None:
    result = subprocess.run(
        ["bash", "-n"], input=_script(), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_swap_only_under_4gb() -> None:
    script = _script()
    assert "/proc/meminfo" in script
    assert "-lt 4096 ]" in script


def test_swapfile_is_created_once_and_persisted() -> None:
    script = _script()
    assert 'if [ ! -f "$SWAPFILE" ]' in script
    assert "mkswap" in script and "swapon" in script
    # fstab entry guarded so a re-run does not append a second line.
    assert 'grep -q "^$SWAPFILE " /etc/fstab ||' in script


def test_swappiness_is_low_and_persisted() -> None:
    script = _script()
    assert "vm.swappiness=10" in script
    assert "/etc/sysctl.d/" in script
