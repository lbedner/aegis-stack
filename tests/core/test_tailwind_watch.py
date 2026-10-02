"""The dev Tailwind watcher cannot stop rebuilding and stay stopped.

``tailwindcss --watch`` once logged a rebuild and then ignored every later
change while its container stayed Up, so new classes silently never reached
``app.css``. Docker does not restart an unhealthy container, so a
healthcheck alone would only have reported it. The watcher runs under
``tailwind_watch.sh``, which restarts it when it exits, or when a source
changed and no build followed by the next check. A build is the
``Done in <n>ms.`` line Tailwind prints, not ``app.css``'s mtime: Tailwind
skips writing an unchanged ``app.css``, so an edit that adds no class
leaves it older than the template on a perfectly healthy watcher.

These run the real script under ``sh`` with a stub ``tailwindcss``.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from aegis.core.component_files import get_template_path

SCRIPT = (
    get_template_path()
    / "{{ project_slug }}"
    / "app/components/web_frontend/tailwind_watch.sh"
)
WEB = "app/components/web_frontend"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")


def _project(tmp_path: Path) -> Path:
    for rel in (f"{WEB}/templates", f"{WEB}/static/js", f"{WEB}/static/dist"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / f"{WEB}/static/input.css").write_text("@tailwind base;\n")
    (tmp_path / f"{WEB}/templates/page.html").write_text("<p></p>\n")
    (tmp_path / "tailwind.config.js").write_text("module.exports = {}\n")
    return tmp_path


def _stub(tmp_path: Path, body: str) -> Path:
    """A ``tailwindcss`` that counts its starts in ``starts``, then ``body``."""
    stub = tmp_path / "tailwindcss"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo start >> "{tmp_path}/starts"\n'
        f'out="{tmp_path}/{WEB}/static/dist/app.css"\n'
        'echo "/* built */" > "$out"\n'
        'echo "Done in 3ms."\n'
        f"{body}\n"
    )
    stub.chmod(0o755)
    return stub


def _run(root: Path, stub: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["sh", str(SCRIPT)],
        env={
            **os.environ,
            "TAILWIND_ROOT": str(root),
            "TAILWIND_BIN": str(stub),
            "TAILWIND_CHECK_SECONDS": "1",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _starts(root: Path) -> int:
    path = root / "starts"
    return len(path.read_text().splitlines()) if path.exists() else 0


def _stop(proc: subprocess.Popen[bytes]) -> str:
    proc.send_signal(signal.SIGTERM)
    _, err = proc.communicate(timeout=10)
    return err.decode()


def test_a_watcher_that_stopped_rebuilding_is_restarted(tmp_path: Path) -> None:
    root = _project(tmp_path)
    proc = _run(root, _stub(root, "exec sleep 600"))
    try:
        time.sleep(1.5)
        assert _starts(root) == 1
        time.sleep(1.1)
        (root / f"{WEB}/templates/page.html").write_text('<p class="mt-4"></p>\n')
        deadline = time.time() + 8
        while _starts(root) < 2 and time.time() < deadline:
            time.sleep(0.2)
    finally:
        err = _stop(proc)
    assert _starts(root) >= 2, err
    assert "was not rebuilt" in err


def test_a_stuck_watcher_is_restarted_after_a_source_is_deleted(
    tmp_path: Path,
) -> None:
    """A deleted file is never newer than the last build, so the list of
    sources is compared too."""
    root = _project(tmp_path)
    extra = root / f"{WEB}/templates/old.html"
    extra.write_text('<p class="mt-8"></p>\n')
    proc = _run(root, _stub(root, "exec sleep 600"))
    try:
        time.sleep(1.5)
        assert _starts(root) == 1
        extra.unlink()
        deadline = time.time() + 8
        while _starts(root) < 2 and time.time() < deadline:
            time.sleep(0.2)
    finally:
        err = _stop(proc)
    assert _starts(root) >= 2, err


def test_a_watcher_that_exits_is_restarted(tmp_path: Path) -> None:
    root = _project(tmp_path)
    proc = _run(root, _stub(root, "exit 1"))
    try:
        deadline = time.time() + 8
        while _starts(root) < 3 and time.time() < deadline:
            time.sleep(0.2)
    finally:
        _stop(proc)
    assert _starts(root) >= 3


def test_an_edit_that_changes_no_css_does_not_restart_it(tmp_path: Path) -> None:
    """A healthy watcher rebuilds (and says so) without rewriting an
    identical app.css; that must not read as a stuck one."""
    root = _project(tmp_path)
    page = root / f"{WEB}/templates/page.html"
    healthy = (
        f'last=$(stat -f %m "{page}" 2>/dev/null || stat -c %Y "{page}")\n'
        "while sleep 0.2; do\n"
        f'  now=$(stat -f %m "{page}" 2>/dev/null || stat -c %Y "{page}")\n'
        '  [ "$now" != "$last" ] && { last=$now; echo "Done in 2ms."; }\n'
        "done"
    )
    proc = _run(root, _stub(root, healthy))
    try:
        time.sleep(1.5)
        page.write_text("<p></p>\n<!-- no new class -->\n")
        time.sleep(4)
    finally:
        _stop(proc)
    assert _starts(root) == 1


def test_a_quiet_project_is_left_alone(tmp_path: Path) -> None:
    root = _project(tmp_path)
    proc = _run(root, _stub(root, "exec sleep 600"))
    try:
        time.sleep(4)
    finally:
        _stop(proc)
    assert _starts(root) == 1


def test_sigterm_stops_it_promptly(tmp_path: Path) -> None:
    """Compose stops the container with SIGTERM; it must not wait out the
    grace period and be killed."""
    root = _project(tmp_path)
    proc = _run(root, _stub(root, "exec sleep 600"))
    time.sleep(1.2)
    started = time.time()
    _stop(proc)
    assert time.time() - started < 3
    assert proc.returncode == 0


def test_the_dev_stack_runs_tailwind_under_the_supervisor() -> None:
    import yaml
    from jinja2 import Environment, FileSystemLoader

    from aegis.core.component_files import get_copier_defaults

    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    compose = yaml.safe_load(
        env.get_template("{{ project_slug }}/docker-compose.dev.yml.jinja").render(
            {**get_copier_defaults(), "project_slug": "demo", "include_htmx": True}
        )
    )
    command = " ".join(compose["services"]["tailwind"]["command"])
    assert "tailwind_watch.sh" in command
    assert "npx tailwindcss" not in command
