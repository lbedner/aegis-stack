"""Regression: `aegis add worker[<backend>]` must honor the chosen backend.

Previously the add path threaded only scheduler_backend and database_engine, so
`aegis add worker[dramatiq]` silently discarded the bracket and installed the
arq default.

The file layout matters too: worker backend variants ship as sibling files
(`pools_dramatiq.py`, `queues/system_taskiq.py`, ...) that init's
`cleanup_components` renames onto the canonical names (Pattern D). The add
path must run the same cleanup, or the project keeps arq code at the
canonical names with every variant file strewn alongside.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aegis.core.copier_manager import load_copier_answers
from tests.cli.test_utils import run_aegis_command


def _variant_leftovers(project: Path) -> list[str]:
    """Every backend-suffixed worker file still present under app/."""
    app_dir = project / "app"
    leftovers = [
        str(p.relative_to(project))
        for suffix in ("_dramatiq.py", "_taskiq.py")
        for p in app_dir.rglob(f"*{suffix}")
    ]
    return sorted(leftovers)


def test_add_worker_dramatiq_honors_backend(
    project_factory: Callable[..., Path],
) -> None:
    project = project_factory("base")

    result = run_aegis_command(
        "add", "worker[dramatiq]", "--project-path", str(project), "--yes"
    )
    assert result.returncode == 0, f"add worker[dramatiq] failed: {result.stderr}"

    answers = load_copier_answers(project)
    assert answers.get("worker_backend") == "dramatiq", (
        f"expected dramatiq, got {answers.get('worker_backend')!r}"
    )
    # The dramatiq dependency must be pulled, not arq's.
    pyproject = (project / "pyproject.toml").read_text()
    assert "dramatiq" in pyproject


def test_add_worker_dramatiq_installs_dramatiq_files(
    project_factory: Callable[..., Path],
) -> None:
    """Canonical worker files must contain dramatiq code, with no variants left.

    Init handles this via cleanup_components' Pattern D renames; the add path
    must produce the same layout or the project runs arq code while its
    answers and dependencies say dramatiq.
    """
    project = project_factory("base")

    result = run_aegis_command(
        "add", "worker[dramatiq]", "--project-path", str(project), "--yes"
    )
    assert result.returncode == 0, f"add worker[dramatiq] failed: {result.stderr}"

    worker_dir = project / "app" / "components" / "worker"
    assert "dramatiq" in (worker_dir / "pools.py").read_text().lower()
    assert "dramatiq" in (worker_dir / "queues" / "system.py").read_text().lower()
    # Dramatiq ships a broker module arq doesn't have; the variant must be
    # renamed onto the canonical name, not left with its suffix.
    assert (worker_dir / "broker.py").exists()
    api_worker = project / "app" / "components" / "backend" / "api" / "worker.py"
    assert "dramatiq" in api_worker.read_text().lower()
    assert "dramatiq" in (worker_dir / "pools.py").read_text().lower()

    assert _variant_leftovers(project) == []


def test_add_worker_taskiq_honors_backend(
    project_factory: Callable[..., Path],
) -> None:
    project = project_factory("base")

    result = run_aegis_command(
        "add", "worker[taskiq]", "--project-path", str(project), "--yes"
    )
    assert result.returncode == 0, f"add worker[taskiq] failed: {result.stderr}"

    answers = load_copier_answers(project)
    assert answers.get("worker_backend") == "taskiq", (
        f"expected taskiq, got {answers.get('worker_backend')!r}"
    )

    worker_dir = project / "app" / "components" / "worker"
    assert "taskiq" in (worker_dir / "pools.py").read_text().lower()
    assert "taskiq" in (worker_dir / "queues" / "system.py").read_text().lower()
    assert (worker_dir / "broker.py").exists()
    assert _variant_leftovers(project) == []


def test_add_worker_default_arq_leaves_no_variant_files(
    project_factory: Callable[..., Path],
) -> None:
    """Plain `aegis add worker` (arq) must strip the dramatiq/taskiq variants."""
    project = project_factory("base")

    result = run_aegis_command("add", "worker", "--project-path", str(project), "--yes")
    assert result.returncode == 0, f"add worker failed: {result.stderr}"

    worker_dir = project / "app" / "components" / "worker"
    pools = (worker_dir / "pools.py").read_text().lower()
    assert "dramatiq" not in pools
    assert "taskiq" not in pools
    # arq has no broker module; nothing should have been renamed onto it.
    assert not (worker_dir / "broker.py").exists()
    assert _variant_leftovers(project) == []


def test_add_worker_rejects_unknown_backend(
    project_factory: Callable[..., Path],
) -> None:
    project = project_factory("base")

    result = run_aegis_command(
        "add", "worker[dramatq]", "--project-path", str(project), "--yes"
    )
    assert result.returncode != 0, "typo backend should be rejected"

    answers = load_copier_answers(project)
    assert answers.get("include_worker") is not True, (
        "rejected add must not enable the worker"
    )
