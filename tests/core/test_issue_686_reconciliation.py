"""Tests for issue #686 — `aegis add-service` clobbering shared files.

Two failure modes:

* **A — empty stubs survive.** Whole-file `{% if include_X %}...{% endif %}`
  templates render as 0-byte / whitespace-only `.py` files at init time when
  the gate is False. Later `add-service` doesn't touch off-manifest paths,
  so the stubs stay empty and crash at import time.
* **B — answer drift drops fields.** When `.copier-answers.yml` is missing
  `include_<service>` flags for a service that's actually installed on
  disk, `_regenerate_shared_files` re-renders `app/core/config.py` with
  those flags False and drops env-bound Settings fields.

The fix has two pieces, tested here:

* :func:`sweep_empty_stubs` — project-wide cleanup of empty .py files.
* :meth:`ManualUpdater.reconcile_answers_from_disk` — infer
  include flags from filesystem markers and persist them before any
  shared-file regen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core.manual_updater import ManualUpdater, sweep_empty_stubs

COPIER_ANSWERS_MINIMAL = """\
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
project_name: Demo
project_slug: demo
_commit: None
_src_path: aegis/templates/copier-aegis-project
"""


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".copier-answers.yml").write_text(COPIER_ANSWERS_MINIMAL)
    return project


# ---------------------------------------------------------------------------
# sweep_empty_stubs
# ---------------------------------------------------------------------------


class TestSweepEmptyStubs:
    def test_deletes_whitespace_only_py_file(self, fake_project: Path) -> None:
        stub = (
            fake_project / "app" / "components" / "frontend" / "auth" / "login_view.py"
        )
        stub.parent.mkdir(parents=True)
        stub.write_text("   \n\n")

        deleted = sweep_empty_stubs(fake_project)

        assert not stub.exists()
        assert "app/components/frontend/auth/login_view.py" in deleted

    def test_deletes_zero_byte_py_file(self, fake_project: Path) -> None:
        stub = fake_project / "app" / "services" / "auth" / "oauth.py"
        stub.parent.mkdir(parents=True)
        stub.write_text("")

        deleted = sweep_empty_stubs(fake_project)

        assert not stub.exists()
        assert "app/services/auth/oauth.py" in deleted

    def test_preserves_non_empty_py_file(self, fake_project: Path) -> None:
        keep = fake_project / "app" / "main.py"
        keep.parent.mkdir(parents=True)
        keep.write_text("print('hi')\n")

        deleted = sweep_empty_stubs(fake_project)

        assert keep.exists()
        assert "app/main.py" not in deleted

    def test_preserves_empty_init_py(self, fake_project: Path) -> None:
        """Empty ``__init__.py`` is meaningful (package marker) — keep it."""
        init = fake_project / "app" / "services" / "auth" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.write_text("")

        sweep_empty_stubs(fake_project)

        assert init.exists()

    def test_skips_venv_and_git(self, fake_project: Path) -> None:
        for ignored in (".venv", ".git", "__pycache__", "node_modules"):
            stub = fake_project / ignored / "stub.py"
            stub.parent.mkdir(parents=True)
            stub.write_text("")

        deleted = sweep_empty_stubs(fake_project)

        for ignored in (".venv", ".git", "__pycache__", "node_modules"):
            assert (fake_project / ignored / "stub.py").exists()
            assert f"{ignored}/stub.py" not in deleted

    def test_skips_alembic_versions(self, fake_project: Path) -> None:
        """Alembic version files can be one-line stubs (down_revision = None);
        they're authored, not generated empties."""
        stub = fake_project / "alembic" / "versions" / "001_init.py"
        stub.parent.mkdir(parents=True)
        stub.write_text("")

        sweep_empty_stubs(fake_project)

        assert stub.exists()

    def test_rmdirs_emptied_parents(self, fake_project: Path) -> None:
        stub = (
            fake_project / "app" / "components" / "frontend" / "auth" / "login_view.py"
        )
        stub.parent.mkdir(parents=True)
        stub.write_text("")

        sweep_empty_stubs(fake_project)

        # auth dir becomes empty -> removed; frontend has other siblings? no -> removed too
        assert not (fake_project / "app" / "components" / "frontend" / "auth").exists()

    def test_keeps_parent_with_other_files(self, fake_project: Path) -> None:
        auth_dir = fake_project / "app" / "components" / "frontend" / "auth"
        auth_dir.mkdir(parents=True)
        (auth_dir / "login_view.py").write_text("")
        (auth_dir / "keep.py").write_text("x = 1\n")

        sweep_empty_stubs(fake_project)

        assert auth_dir.exists()
        assert (auth_dir / "keep.py").exists()


# ---------------------------------------------------------------------------
# reconcile_answers_from_disk
# ---------------------------------------------------------------------------


def _seed_answers(project: Path, body: str) -> None:
    (project / ".copier-answers.yml").write_text(body)


# (service module, orgs module) at the current names and at the names the
# auth restructure replaced, so an older project still infers on update.
AUTH_LAYOUTS = [
    pytest.param("service.py", "orgs.py", id="current-layout"),
    pytest.param("auth_service.py", "org_service.py", id="pre-restructure-layout"),
]


class TestReconcileAnswersFromDisk:
    def test_infers_include_insights_from_services_dir(
        self, fake_project: Path
    ) -> None:
        (fake_project / "app" / "services" / "insights").mkdir(parents=True)
        (fake_project / "app" / "services" / "insights" / "__init__.py").write_text("")
        (
            fake_project / "app" / "services" / "insights" / "collector_service.py"
        ).write_text("x = 1\n")

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("include_insights") is True

    @pytest.mark.parametrize(("service_name", "orgs_name"), AUTH_LAYOUTS)
    def test_infers_include_auth_from_auth_service_module(
        self, fake_project: Path, service_name: str, orgs_name: str
    ) -> None:
        auth_svc = fake_project / "app" / "services" / "auth" / service_name
        auth_svc.parent.mkdir(parents=True)
        auth_svc.write_text("class AuthService: ...\n")

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("include_auth") is True

    @pytest.mark.parametrize(("service_name", "orgs_name"), AUTH_LAYOUTS)
    def test_infers_auth_level_org_from_org_service(
        self, fake_project: Path, service_name: str, orgs_name: str
    ) -> None:
        auth_svc = fake_project / "app" / "services" / "auth" / service_name
        auth_svc.parent.mkdir(parents=True)
        auth_svc.write_text("class AuthService: ...\n")
        org_svc = fake_project / "app" / "services" / "auth" / orgs_name
        org_svc.write_text("class OrgService: ...\n")

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("auth_level") == "org"

    @pytest.mark.parametrize(("service_name", "orgs_name"), AUTH_LAYOUTS)
    def test_infers_auth_level_rbac_from_require_role_symbol(
        self, fake_project: Path, service_name: str, orgs_name: str
    ) -> None:
        """RBAC has no dedicated module — it's an inline gate. Sniff
        ``def require_role`` in the rendered auth service module instead."""
        auth_svc = fake_project / "app" / "services" / "auth" / service_name
        auth_svc.parent.mkdir(parents=True)
        auth_svc.write_text(
            "class AuthService: ...\n\n"
            "def require_role(*required_roles: str):\n"
            "    ...\n"
        )

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("auth_level") == "rbac"
        assert inferred.get("include_auth_rbac") is True

    @pytest.mark.parametrize(("service_name", "orgs_name"), AUTH_LAYOUTS)
    def test_does_not_infer_rbac_when_require_role_absent(
        self, fake_project: Path, service_name: str, orgs_name: str
    ) -> None:
        """Basic auth (no RBAC) — the service module exists but lacks
        ``def require_role``. Must not flip RBAC on."""
        auth_svc = fake_project / "app" / "services" / "auth" / service_name
        auth_svc.parent.mkdir(parents=True)
        auth_svc.write_text("class AuthService: ...\n")

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("auth_level") != "rbac"
        assert inferred.get("include_auth_rbac") is not True

    def test_infers_include_ai_from_service_package(self, fake_project: Path) -> None:
        """AI's entry point is the ``service`` package, not a flat module;
        any non-stub file under the service counts."""
        service = fake_project / "app" / "services" / "ai" / "service"
        service.mkdir(parents=True)
        (service / "__init__.py").write_text("class AIService: ...\n")
        (service / "chat.py").write_text("class ChatMixin: ...\n")

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("include_ai") is True

    def test_never_demotes_existing_true_flag(self, fake_project: Path) -> None:
        """Disk has no insights marker, but answers say True. Reconcile must
        not flip True → False."""
        _seed_answers(
            fake_project,
            COPIER_ANSWERS_MINIMAL + "include_insights: true\n",
        )

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        # Reconcile only proposes promotions. The reconcile method itself
        # should not include a False override for include_insights.
        assert inferred.get("include_insights") is not False

    def test_infers_insights_sub_flags_from_collectors(
        self, fake_project: Path
    ) -> None:
        collectors = (
            fake_project / "app" / "services" / "insights" / "adapters" / "collectors"
        )
        collectors.mkdir(parents=True)
        (collectors / "collection.py").write_text(
            "from x import GitHubTrafficCollector, PyPICollector\n"
        )

        updater = ManualUpdater(fake_project)
        inferred = updater.reconcile_answers_from_disk()

        assert inferred.get("insights_github") is True
        assert inferred.get("insights_pypi") is True


class TestManualUpdaterInitPersistsReconciliation:
    def test_init_writes_inferred_flags_to_answers_file(
        self, fake_project: Path
    ) -> None:
        (fake_project / "app" / "services" / "insights").mkdir(parents=True)
        (
            fake_project / "app" / "services" / "insights" / "collector_service.py"
        ).write_text("x = 1\n")

        # Sanity: answers file has no include_insights pre-init
        before = (fake_project / ".copier-answers.yml").read_text()
        assert "include_insights" not in before

        ManualUpdater(fake_project)

        after = (fake_project / ".copier-answers.yml").read_text()
        assert "include_insights: true" in after.lower()

    def test_init_no_op_when_disk_and_answers_agree(self, fake_project: Path) -> None:
        """If reconcile finds nothing new, don't rewrite the file (avoids
        spurious diffs / timestamps)."""
        before_mtime = (fake_project / ".copier-answers.yml").stat().st_mtime_ns

        ManualUpdater(fake_project)

        after_mtime = (fake_project / ".copier-answers.yml").stat().st_mtime_ns
        assert before_mtime == after_mtime


# Integration tests live in tests/cli/test_issue_686_integration.py —
# they depend on the ``project_factory`` fixture from tests/cli/conftest.py.
