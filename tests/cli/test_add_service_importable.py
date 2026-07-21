"""Importability smoke test: ``add-service <svc>`` must leave a project that imports.

The completeness guard (``test_shared_files_completeness.py``) validates the
``aegis update`` story by diffing init-generated stacks, but it never exercises
the ``add-service`` regeneration path and never imports the result. That gap let
a real bug ship: ``add-service auth`` on a no-auth project left
``core/routes.py`` on its pre-auth render and never created
``auth_sessions_tab.py``, so the webserver crash-looped on
``ImportError: cannot import name 'REGISTER_ROUTE'`` — a failure no test caught.

This test closes the class for every service: add each service to a base
project, then import the webserver / CLI / backend-routing entry chains in the
generated project's own virtualenv. A missing constant, a stale conditional
render, or an unwritten module surfaces here as a non-zero import exit.

Imports run via ``uv run`` inside the project because the generated app depends
on packages (flet, fastapi, sqlmodel, service SDKs) that are not installed in
the test interpreter; ``add-service`` has already synced the project venv.
"""

import shutil

import pytest

from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command, run_project_command

# One invocation per service in the SERVICES registry. Bracket options are used
# where the service would otherwise prompt interactively (``ai``).
SERVICE_INVOCATIONS: tuple[str, ...] = (
    "auth",
    "ai[sqlite]",
    "comms",
    "insights",
    "payment",
    "blog",
    "finance",
)

# Entry chains the webserver and CLI import at process start. Importing
# ``app.integrations.main`` pulls in the frontend dashboard (cards -> modals ->
# service tabs -> core routes), which is the exact chain that broke for auth.
_IMPORT_PROBE = (
    "import app.integrations.main; "
    "import app.cli.main; "
    "import app.components.backend.api.routing"
)


class TestAddServiceProducesImportableProject:
    """Every service must add cleanly and leave an importable project."""

    @pytest.mark.slow
    @pytest.mark.parametrize("service", SERVICE_INVOCATIONS)
    def test_service_imports_after_add(
        self, project_factory: ProjectFactory, service: str
    ) -> None:
        project_path = project_factory("base_with_database")

        # ``project_factory`` copies the cached ``.venv`` too, but a relocated
        # uv venv has a broken interpreter (wrong Python / dangling libpython).
        # Drop it so ``add-service``'s own ``uv sync`` rebuilds a working venv
        # in place — matching the install fixtures that exclude ``.venv``.
        shutil.rmtree(project_path / ".venv", ignore_errors=True)

        add = run_aegis_command(
            "add-service",
            service,
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert add.returncode == 0, f"add-service {service} failed:\n{add.stderr}"

        check = run_project_command(
            ["uv", "run", "python", "-c", _IMPORT_PROBE],
            project_path=project_path,
            timeout=300,
            step_name=f"import check ({service})",
        )
        assert check.returncode == 0, (
            f"generated project does not import after add-service {service} "
            f"(the add-service regeneration left the tree inconsistent):\n"
            f"{check.stderr}"
        )
