"""Regression tests for issue #686.

`aegis add-service` must not destroy state that earlier services
contributed to the project. Two failure modes are tracked:

* Failure A (empty stub survival): templates gated end-to-end with
  ``{% if include_<svc> -%} ... {%- endif %}`` write 0-byte files at
  init time. On a later ``add-service``, those files exist on disk so
  the merge step skips them as "user files," leaving the service
  scaffolding empty.

* Failure B (shared-file clobbering): files in
  the shared-file scope (notably ``app/core/config.py``; then a hand-
  maintained list in ``aegis/config/shared_files.py``, now derived)
  are re-rendered on ``add-service`` and lose fields contributed by
  previously-installed services if the merge of answers is missing
  any flag.

Both tests start from the cached ``insights_full`` skeleton (database
+ scheduler + insights service) and run ``add-service auth`` on top.
"""

import pytest

from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command


class TestAddServicePreservesPriorServiceState:
    """add-service auth on a project with insights must keep insights working."""

    @pytest.mark.slow
    def test_add_auth_does_not_leave_empty_auth_view_stubs(
        self, project_factory: ProjectFactory
    ) -> None:
        """Failure A: auth scaffolding must not be empty after add-service.

        At init time without auth, the gated auth templates wrote 0-byte
        files. When add-service auth runs, those existing empty files
        survived the merge. The frontend then crashed on
        ``cannot import name 'LoginView' from ...login_view``.
        """
        project_path = project_factory("insights_full")

        # Sanity: the project has insights, no auth.
        config = (project_path / "app/core/config.py").read_text()
        assert "INSIGHT_GITHUB_OWNER" in config, (
            "fixture should already contain insights fields"
        )

        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"add-service failed: {result.stderr}"

        login_view = project_path / "app/components/frontend/auth/login_view.py"
        assert login_view.exists(), "login_view.py should exist after add-service auth"

        body = login_view.read_text().strip()
        assert body, "login_view.py is empty — gated empty stub survived add-service"
        assert "class LoginView" in body, (
            f"login_view.py should define LoginView, got {len(body)} bytes:\n{body[:200]}"
        )

    @pytest.mark.slow
    def test_add_auth_keeps_insights_settings_fields(
        self, project_factory: ProjectFactory
    ) -> None:
        """Failure B: app/core/config.py must keep insights fields after add-service.

        Before: re-rendering config.py with only the new service's flags
        active dropped INSIGHT_GITHUB_OWNER and friends from the
        Settings class. The .env still carries those vars, so Pydantic
        rejected them as ``Extra inputs are not permitted`` on next boot.
        """
        project_path = project_factory("insights_full")

        config_path = project_path / "app/core/config.py"
        before = config_path.read_text()
        assert "INSIGHT_GITHUB_OWNER" in before, (
            "fixture should already contain INSIGHT_GITHUB_OWNER"
        )

        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"add-service failed: {result.stderr}"

        after = config_path.read_text()
        # Auth must be present (sanity for add-service itself).
        assert "JWT_ALGORITHM" in after or "ACCESS_TOKEN_EXPIRE_MINUTES" in after, (
            "add-service auth did not add auth fields to config.py"
        )
        # Insights must still be present (the actual regression).
        assert "INSIGHT_GITHUB_OWNER" in after, (
            "add-service auth dropped INSIGHT_GITHUB_OWNER from config.py"
        )
        assert "INSIGHT_COLLECTION_GITHUB_HOURS" in after, (
            "add-service auth dropped INSIGHT_COLLECTION_GITHUB_HOURS from config.py"
        )
