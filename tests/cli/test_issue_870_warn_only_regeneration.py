"""Regression tests for issue #870 — stale warn-only Dockerfiles.

Rewritten for aegis-stack#919 (RD-04): the render-diff engine has no
patchable ``SHARED_TEMPLATE_FILES`` dict, and its ``ManualUpdater`` needs a
real ``jinja_env``/``template_path`` (set up in ``__init__``, which the old
version of these tests bypassed via ``ManualUpdater.__new__``). These now
run against a real generated project and the real ``Dockerfile.jinja``,
whose ``{#- aegis: warn-if-diverged -#}`` annotation (aegis-stack#917) is
what encodes the policy the old tests hand-patched into a dict.
"""

from __future__ import annotations

import pytest

from aegis.core.manual_updater import ManualUpdater
from tests.cli.conftest import ProjectFactory

pytestmark = pytest.mark.xdist_group("generated_stacks")


class TestPristineDockerfileRegeneratesOnHtmxChange:
    def test_htmx_off_to_on(self, project_factory: ProjectFactory) -> None:
        project = project_factory("base")  # include_htmx: False, pristine
        updater = ManualUpdater(project)

        updated, _, need_merge = updater._regenerate_shared_files(
            {**updater.answers, "include_htmx": True}
        )

        assert "Dockerfile" in updated
        assert "Dockerfile" not in need_merge
        assert "css-build" in (project / "Dockerfile").read_text()

    def test_htmx_on_to_off(self, project_factory: ProjectFactory) -> None:
        project = project_factory("base_htmx")  # include_htmx: True, pristine
        updater = ManualUpdater(project)

        updated, _, need_merge = updater._regenerate_shared_files(
            {**updater.answers, "include_htmx": False}
        )

        assert "Dockerfile" in updated
        assert "Dockerfile" not in need_merge
        content = (project / "Dockerfile").read_text()
        assert "FROM python" in content
        assert "css-build" not in content


def test_htmx_change_preserves_custom_dockerfile(
    project_factory: ProjectFactory,
) -> None:
    """The Dockerfile only partly owns its content (issue #870's htmx
    css-build stage); a hand-edited copy must never be merged — merging
    could mangle custom build steps the template can't reproduce."""
    project = project_factory("base")
    dockerfile = project / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text() + "\nRUN custom-build-step\n")
    before = dockerfile.read_text()

    updater = ManualUpdater(project)
    updated, _, need_merge = updater._regenerate_shared_files(
        {**updater.answers, "include_htmx": True}
    )

    assert dockerfile.read_text() == before
    assert "Dockerfile" not in updated
    assert "Dockerfile" in need_merge
