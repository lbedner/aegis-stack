"""Issue #814 follow-up: add-service must converge on fresh-init output.

The full-service audit (fresh ``init --services S`` vs ``base init +
add-service S``, same slug, tree+content diff) found four classes of miss:

1. Stale conditional wiring in files absent from the then-current shared-file
   list (``SHARED_TEMPLATE_FILES``, since deleted in favour of a derived scope
   — aegis-stack#922) —
   including auth gates on ``metrics.py``/``task_history.py`` (security) and
   job registration in ``scheduler/main.py`` (silent no-op collectors).
2. Regen machinery bugs: ruff normalization under a temp filename bypasses the
   generated project's ``per-file-ignores`` (deps.py re-exports stripped), and
   the updater's Jinja env dropped every regenerated file's trailing newline.
3. Manifest over-copy: auth's org-gated and htmx-gated files rode ``primary``
   into basic/non-htmx projects.
4. Gated-on-arrival files never materialized: the ``add-model-and-migration``
   skill when the first migration-bearing service lands.
"""

from __future__ import annotations

import pytest

from aegis.core.component_files import get_component_files
from aegis.core.manual_updater import ManualUpdater
from aegis.core.template_cleanup import ruff_executable, run_ruff_on_text
from tests.cli.conftest import ProjectFactory

# Regen shells out to ruff/git per file; serialize away from the fork-heavy
# stacks tests like the sibling #715 suites.
pytestmark = pytest.mark.xdist_group("generated_stacks")

DEPS_FILE = "app/components/backend/api/deps.py"
METRICS_FILE = "app/components/backend/api/metrics.py"
SCHEDULER_MAIN = "app/components/scheduler/main.py"
MIGRATION_SKILL = ".claude/skills/add-model-and-migration/SKILL.md"


class TestRegenFidelity:
    """Regenerated files must be byte-faithful to what init produces."""

    def test_regen_preserves_trailing_newline(
        self, project_factory: ProjectFactory
    ) -> None:
        """Copier renders with ``keep_trailing_newline=True``; the updater's
        env must match or every regen churns the final newline."""
        project = project_factory("base")
        updater = ManualUpdater(project)
        updater._regenerate_shared_files({**updater.answers, "include_redis": True})

        content = (project / "docker-compose.yml").read_text()
        assert content.endswith("\n"), "regen dropped the trailing newline"

    def test_ruff_normalize_respects_per_file_ignores(
        self, project_factory: ProjectFactory
    ) -> None:
        """Normalizing under the file's real relative path keeps rules like
        deps.py's F401 ignore in force; a temp filename silently loses them."""
        if ruff_executable() is None:
            pytest.skip("ruff not available")
        project = project_factory("base")
        src = '"""Re-export shim."""\n\nfrom app.core.config import settings\n'

        result = run_ruff_on_text(src, project, "", rel_path=DEPS_FILE)

        assert result is not None
        assert "settings" in result, (
            "per-file-ignores (F401) must apply during normalization"
        )

    def test_deps_reexports_survive_shared_regen(
        self, project_factory: ProjectFactory
    ) -> None:
        """The end-to-end symptom: regen for a payment add must leave the
        payment re-export in deps.py instead of ruff stripping it."""
        project = project_factory("base_with_database")
        updater = ManualUpdater(project)
        updater._regenerate_shared_files({**updater.answers, "include_payment": True})

        assert "get_payment_service" in (project / DEPS_FILE).read_text(), (
            "deps.py re-export was stripped during regen (per-file-ignores lost)"
        )


class TestPromotedWiringFiles:
    """Stack-conditional files that must regenerate on a stack change.

    Named for the old ``SHARED_TEMPLATE_FILES`` promotion that fixed them;
    they are now in scope automatically because no manifest owns them.
    """

    def test_metrics_gains_auth_gate_on_regen(
        self, project_factory: ProjectFactory
    ) -> None:
        """SECURITY: a fresh auth stack protects /metrics; the retrofit must
        too, not leave the pre-auth default-open render."""
        project = project_factory("base")
        updater = ManualUpdater(project)
        updater._regenerate_shared_files({**updater.answers, "include_auth": True})

        assert "get_current_active_user" in (project / METRICS_FILE).read_text(), (
            "metrics endpoint left unprotected after auth add"
        )

    def test_scheduler_main_gains_insights_jobs(
        self, project_factory: ProjectFactory
    ) -> None:
        """add-service insights must register its jobs, or collectors
        silently never run."""
        project = project_factory("scheduler_and_database")
        updater = ManualUpdater(project)
        updater._regenerate_shared_files(
            {
                **updater.answers,
                "include_insights": True,
                "insights_github": True,
            }
        )

        assert "insights" in (project / SCHEDULER_MAIN).read_text(), (
            "scheduler/main.py never registered the insights jobs"
        )

    def test_scheduler_main_not_created_without_component(
        self, project_factory: ProjectFactory
    ) -> None:
        """A component-owned promoted file must regenerate where it exists but
        never be created in a project without its component."""
        project = project_factory("base")  # no scheduler
        updater = ManualUpdater(project)
        updater._regenerate_shared_files({**updater.answers, "include_insights": True})

        assert not (project / SCHEDULER_MAIN).exists(), (
            "regen materialized a scheduler file in a scheduler-less project"
        )


class TestGatedOnArrival:
    """Files inline-removed at init must come back when their gate flips on."""

    def test_migration_skill_created_when_service_arrives(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base_with_database")
        assert not (project / MIGRATION_SKILL).exists()  # no migrations yet

        updater = ManualUpdater(project)
        result = updater.add_component("payment", run_post_gen=False)

        assert result.success, result.error_message
        assert (project / MIGRATION_SKILL).exists(), (
            "add-model-and-migration skill missing after a migration service"
        )


class TestAuthManifestGating:
    """Auth's org-gated and htmx-gated files stay out of ungated projects."""

    def test_add_base_excludes_gated_files_by_default(self) -> None:
        files = set(get_component_files("auth"))
        assert "app/models/org.py" not in files
        assert not any(f.startswith("app/components/backend/api/orgs") for f in files)
        assert not any(f.startswith("app/components/web_frontend") for f in files)

    def test_answers_pull_in_matching_extras(self) -> None:
        files = set(
            get_component_files(
                "auth", answers={"include_auth_org": True, "include_htmx": True}
            )
        )
        assert "app/models/org.py" in files
        assert any(f.startswith("app/components/backend/api/orgs") for f in files)
        assert any(f.startswith("app/components/web_frontend") for f in files)

    def test_add_auth_basic_writes_no_org_or_htmx_files(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base")
        updater = ManualUpdater(project)
        result = updater.add_component(
            "auth", {"auth_level": "basic"}, run_post_gen=False
        )

        assert result.success, result.error_message
        assert not (project / "app/models/org.py").exists()
        assert not (project / "app/components/backend/api/orgs").exists()
        assert not (project / "app/components/web_frontend").exists()
        assert not (
            project / "app/components/frontend/dashboard/modals/auth_orgs_tab.py"
        ).exists()
