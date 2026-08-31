"""``aegis add ingress`` must populate its whole-file-gated deploy files.

Three shared files are wrapped entirely in ``{%- if include_ingress -%}``:
``docker-compose.prod.yml``, ``.env.deploy.example``, and
``scripts/server-setup.sh``. On a project without ingress they render to
a single newline — a 1-byte stub that ships in every base project.

Adding ingress has to fill them in. The stub is what the template
currently produces, so it is pristine and safe to overwrite; treating it
as hand-edited content leaves the file empty forever. None of the three
is a ``.py`` file, so ``sweep_empty_stubs`` never cleans them up either —
the project would simply ship an empty production compose override and
an empty deploy config, with nothing to signal it.

Regression guard for the ``base_empty`` short-circuit in
``RenderDiffEngine._classify`` (aegis-stack#916/#919).
"""

from __future__ import annotations

import pytest

from aegis.core.manual_updater import ManualUpdater
from tests.cli.conftest import ProjectFactory

pytestmark = pytest.mark.xdist_group("generated_stacks")

GATED_DEPLOY_FILES = (
    "docker-compose.prod.yml",
    ".env.deploy.example",
    "scripts/server-setup.sh",
)


class TestAddIngressPopulatesGatedDeployFiles:
    def test_base_project_ships_them_as_stubs(
        self, project_factory: ProjectFactory
    ) -> None:
        """Establishes the precondition the fix depends on — if these ever
        stop shipping as stubs, the scenario below is no longer the one
        being guarded and this file needs revisiting."""
        project = project_factory("base")

        for rel_path in GATED_DEPLOY_FILES:
            path = project / rel_path
            assert path.is_file(), f"{rel_path} is not shipped at all"
            assert not path.read_text().strip(), (
                f"{rel_path} is no longer an empty stub in a base project"
            )

    def test_adding_ingress_fills_them_in(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base")

        updater = ManualUpdater(project)
        updater._regenerate_shared_files({**updater.answers, "include_ingress": True})

        for rel_path in GATED_DEPLOY_FILES:
            content = (project / rel_path).read_text()
            assert content.strip(), (
                f"{rel_path} is still an empty stub after adding ingress — "
                "the gated file was misread as user content and preserved"
            )

    def test_reported_as_updated(self, project_factory: ProjectFactory) -> None:
        """They must also show up in the result, so ``aegis add``'s output
        reflects that the deploy files were written."""
        project = project_factory("base")

        updater = ManualUpdater(project)
        updated, _, _ = updater._regenerate_shared_files(
            {**updater.answers, "include_ingress": True}
        )

        for rel_path in GATED_DEPLOY_FILES:
            assert rel_path in updated, f"{rel_path} missing from the update report"


class TestRemovingIngressDropsTheDeployFiles:
    """The reverse direction, pinned because it is a deliberate asymmetry.

    Turning the gate back off *deletes* these files rather than truncating
    them to stubs, so a removal leaves a slightly different tree than a
    fresh init without ingress (absent vs. 1-byte stub). That is safe:
    every consumer is gated on the same flag and regenerates alongside
    them — the Makefile's ``COMPOSE_PROD`` drops its
    ``-f docker-compose.prod.yml`` when ingress goes away.
    """

    def test_gate_off_deletes_rather_than_restubs(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base")

        # Populate them first (add ingress), then take it away.
        updater = ManualUpdater(project)
        with_ingress = {**updater.answers, "include_ingress": True}
        updater._regenerate_shared_files(with_ingress)
        updater.answers = with_ingress

        updater._regenerate_shared_files({**with_ingress, "include_ingress": False})

        for rel_path in GATED_DEPLOY_FILES:
            assert not (project / rel_path).exists(), (
                f"{rel_path} survived ingress removal"
            )

    def test_makefile_stops_referencing_the_deleted_compose_file(
        self, project_factory: ProjectFactory
    ) -> None:
        """The reason deleting is safe — the consumer regenerates in the
        same pass. If this ever fails, deletion becomes a broken-reference
        bug and the asymmetry needs revisiting."""
        project = project_factory("base")

        updater = ManualUpdater(project)
        with_ingress = {**updater.answers, "include_ingress": True}
        updater._regenerate_shared_files(with_ingress)
        updater.answers = with_ingress

        updater._regenerate_shared_files({**with_ingress, "include_ingress": False})

        assert "docker-compose.prod.yml" not in (project / "Makefile").read_text()
