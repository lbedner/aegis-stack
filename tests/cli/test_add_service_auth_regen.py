"""Regression test: ``aegis add-service auth`` must produce a bootable project.

On a project generated without auth, several auth-conditional frontend files
were left on their pre-auth render (they were not in
the shared-file list of the day, ``aegis/config/shared_files.py``, since
replaced by a derived scope — so the updater never regenerated them), and
``auth_sessions_tab.py`` was never created (it was missing from the auth
``FileManifest``). The webserver then crash-looped on::

    ImportError: cannot import name 'REGISTER_ROUTE' from
    'app.components.frontend.core.routes'

and, behind that, on the missing ``AuthSessionsTab`` import in
``auth_modal.py``. These assertions encode that the regeneration now covers the
full auth chain.

Starts from the cached ``base_with_database`` skeleton (database, no auth) and
runs ``add-service auth`` on top.
"""

import pytest

from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command


class TestAddServiceAuthRegeneratesSharedFrontendFiles:
    """add-service auth must regenerate auth-gated shared frontend files."""

    @pytest.mark.slow
    def test_add_auth_renders_auth_routes_and_sessions_tab(
        self, project_factory: ProjectFactory
    ) -> None:
        project_path = project_factory("base_with_database")

        # Sanity: pre-auth render has no auth routes.
        routes_path = project_path / "app/components/frontend/core/routes.py"
        assert "REGISTER_ROUTE" not in routes_path.read_text(), (
            "fixture should not have auth routes before add-service auth"
        )

        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"add-service failed: {result.stderr}"

        # routes.py must gain the auth route constants (the original crash).
        routes = routes_path.read_text()
        assert "REGISTER_ROUTE" in routes and "LOGIN_ROUTE" in routes, (
            "add-service auth did not regenerate core/routes.py with auth routes"
        )

        # routing.py must gain the auth redirect-to-login guard (next crash).
        routing = (project_path / "app/components/frontend/core/routing.py").read_text()
        assert "LOGIN_ROUTE" in routing, (
            "add-service auth did not regenerate core/routing.py with the auth guard"
        )

        # auth_sessions_tab.py must be created (auth_modal.py imports it).
        sessions_tab = (
            project_path
            / "app/components/frontend/dashboard/modals/auth_sessions_tab.py"
        )
        assert sessions_tab.exists(), (
            "auth_sessions_tab.py was not created by add-service auth"
        )
        assert "class AuthSessionsTab" in sessions_tab.read_text(), (
            "auth_sessions_tab.py is present but does not define AuthSessionsTab"
        )

        # The modal that imports it must keep that import (cross-check the chain).
        auth_modal = (
            project_path / "app/components/frontend/dashboard/modals/auth_modal.py"
        ).read_text()
        assert "from .auth_sessions_tab import AuthSessionsTab" in auth_modal, (
            "auth_modal.py should import AuthSessionsTab"
        )
