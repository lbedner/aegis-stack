"""
ManualUpdater plugin-template integration test.

Exercises ``ManualUpdater.install_plugin_template_tree`` end-to-end:
the in-repo fake plugin (``tests.fixtures.aegis_plugin_test``) ships
a tiny ``templates/{{ project_slug }}/...`` tree. This test installs
it into a synthetic project directory and verifies the rendered files
land at the right paths with ``{{ project_slug }}`` substituted.

This is the round-8a proof point for plugin distribution: a plugin's
own template files reach the project tree via the same Jinja2
machinery aegis-stack uses for its own templates.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aegis.core.manual_updater import ManualUpdater, _safe_path_segment

# Make sure the in-repo fake plugin is importable via importlib.resources.
TESTS_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
if str(TESTS_FIXTURES) not in sys.path:
    sys.path.insert(0, str(TESTS_FIXTURES))


COPIER_ANSWERS_TEMPLATE = """\
# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
project_name: Demo Project
project_slug: demo-project
include_database: false
_commit: None
_src_path: aegis/templates/copier-aegis-project
"""


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """A directory shaped like a Copier-generated Aegis project, just
    enough for ManualUpdater to bind to it. We don't need the project's
    own files for these tests — only the answers file and a project-slug
    name."""
    project = tmp_path / "demo-project"
    project.mkdir()
    (project / ".copier-answers.yml").write_text(COPIER_ANSWERS_TEMPLATE)
    return project


class TestAddRemovePluginRoundTrip:
    """End-to-end add → answers updated, files dropped → remove → answers
    cleaned, files gone. Mocks out the post-gen hook (``uv sync`` /
    ``make fix``) since the synthetic project isn't a real package."""

    def test_add_writes_plugins_entry(
        self, fake_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from aegis_plugin_test.spec import get_spec

        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        # Skip shared file regen — synthetic project has no shared
        # template files; we're only verifying answers + plugin tree.
        monkeypatch.setattr(
            ManualUpdater,
            "_regenerate_shared_files",
            lambda self, ans: ([], [], []),
        )

        updater = ManualUpdater(fake_project)
        result = updater.add_plugin(
            spec=get_spec(),
            plugin_module_name="aegis_plugin_test",
        )

        assert result.success
        # Plugin entry present in answers + persisted to disk.
        assert any(p.get("name") == "test_plugin" for p in updater.answers["_plugins"])

    def test_remove_drops_entry_and_files(
        self, fake_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from aegis_plugin_test.spec import get_spec

        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        monkeypatch.setattr(
            ManualUpdater,
            "_regenerate_shared_files",
            lambda self, ans: ([], [], []),
        )

        updater = ManualUpdater(fake_project)
        spec = get_spec()
        updater.add_plugin(spec=spec, plugin_module_name="aegis_plugin_test")
        plugin_dir = fake_project / "app" / "services" / "test_plugin"
        assert plugin_dir.exists()

        # Re-bind: ManualUpdater caches answers at construction, and
        # ``_save_answers`` mutates ``self.answers``, so the existing
        # instance is fine for remove. But constructing a fresh updater
        # mirrors how the CLI works (separate add / remove invocations).
        updater = ManualUpdater(fake_project)
        result = updater.remove_plugin(spec)

        assert result.success
        assert not plugin_dir.exists()
        assert not any(
            p.get("name") == "test_plugin"
            for p in (updater.answers.get("_plugins") or [])
        )

    def test_remove_uninstalled_plugin_fails_cleanly(
        self, fake_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from aegis_plugin_test.spec import get_spec

        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        monkeypatch.setattr(
            ManualUpdater,
            "_regenerate_shared_files",
            lambda self, ans: ([], [], []),
        )

        updater = ManualUpdater(fake_project)
        result = updater.remove_plugin(get_spec())

        assert not result.success
        assert "not installed" in (result.error_message or "")

    def test_add_is_idempotent(
        self, fake_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adding the same plugin twice replaces the entry rather than
        duplicating it."""
        from aegis_plugin_test.spec import get_spec

        monkeypatch.setattr(
            ManualUpdater, "run_post_generation_tasks", lambda self: None
        )
        monkeypatch.setattr(
            ManualUpdater,
            "_regenerate_shared_files",
            lambda self, ans: ([], [], []),
        )

        updater = ManualUpdater(fake_project)
        spec = get_spec()
        updater.add_plugin(spec=spec, plugin_module_name="aegis_plugin_test")
        # Re-bind so we read latest answers from disk.
        updater = ManualUpdater(fake_project)
        updater.add_plugin(spec=spec, plugin_module_name="aegis_plugin_test")

        plugin_entries = [
            p for p in updater.answers["_plugins"] if p.get("name") == "test_plugin"
        ]
        assert len(plugin_entries) == 1


class TestInstallPluginTemplateTree:
    def test_renders_plugin_files_into_project(self, fake_project: Path) -> None:
        updater = ManualUpdater(fake_project)
        written = updater.install_plugin_template_tree("aegis_plugin_test")

        # Two .jinja files in the fake plugin: __init__.py.jinja +
        # service.py.jinja, both under app/services/test_plugin/.
        assert sorted(written) == sorted(
            [
                "app/services/test_plugin/__init__.py",
                "app/services/test_plugin/service.py",
            ]
        )

    def test_files_land_at_expected_paths(self, fake_project: Path) -> None:
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")

        init_file = fake_project / "app/services/test_plugin/__init__.py"
        service_file = fake_project / "app/services/test_plugin/service.py"
        assert init_file.is_file()
        assert service_file.is_file()

    def test_jinja_rendered_with_project_answers(self, fake_project: Path) -> None:
        """The plugin template references ``{{ project_slug }}`` —
        confirm it was substituted with the project's actual slug."""
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")

        init_content = (
            fake_project / "app/services/test_plugin/__init__.py"
        ).read_text()
        assert 'PLUGIN_NAME = "demo-project-test-plugin"' in init_content

        service_content = (
            fake_project / "app/services/test_plugin/service.py"
        ).read_text()
        assert 'project_slug = "demo-project"' in service_content

    def test_pure_code_plugin_returns_empty_list(self, fake_project: Path) -> None:
        """Plugins without a ``templates/`` dir (pure-code plugins —
        wiring data only) return an empty list and write nothing."""
        updater = ManualUpdater(fake_project)
        # ``json`` is a stdlib package without templates; resolver
        # returns None → install method short-circuits.
        written = updater.install_plugin_template_tree("json")
        assert written == []

    def test_overwrites_existing_files(self, fake_project: Path) -> None:
        """Re-running install on the same plugin overwrites — the test
        plugin's content should be deterministic, so the second run
        produces the same output.

        Plugin files are vendored artifacts owned by the plugin, not
        scaffolding the project takes ownership of: an upgrade re-renders
        them wholesale, the same way ``npm update`` replaces a package
        rather than merging your edits to it. Local edits are replaced —
        see ``TestPluginOverwriteIsBackedUp`` for the guarantee that they
        are never destroyed *silently*.
        """
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")
        first_content = (
            fake_project / "app/services/test_plugin/service.py"
        ).read_text()

        # Tamper with the file, then re-install.
        (fake_project / "app/services/test_plugin/service.py").write_text("tampered")
        updater.install_plugin_template_tree("aegis_plugin_test")

        second_content = (
            fake_project / "app/services/test_plugin/service.py"
        ).read_text()
        assert second_content == first_content


SERVICE_FILE = "app/services/test_plugin/service.py"


class TestPluginOverwriteIsBackedUp:
    """Overwriting is correct; overwriting *silently* is not.

    Plugin files land in the user's own repo, next to their code, so
    "this is vendored, don't edit it" is not self-evident the way
    ``node_modules/`` is. When an upgrade replaces a file whose content
    differs from what we're about to write, the previous content is
    snapshotted under ``.aegis/plugin-backups/`` (already gitignored in
    generated projects, alongside ``deploy.yml``) and reported, so the
    user can recover an edit they'd otherwise lose without warning.
    """

    def test_first_install_backs_up_nothing(self, fake_project: Path) -> None:
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")

        assert not (fake_project / ".aegis" / "plugin-backups").exists()

    def test_identical_reinstall_backs_up_nothing(self, fake_project: Path) -> None:
        """A no-op re-render must not litter backups — only genuinely
        replaced content is worth snapshotting."""
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")
        updater.install_plugin_template_tree("aegis_plugin_test")

        assert not (fake_project / ".aegis" / "plugin-backups").exists()

    def test_replaced_local_edit_is_snapshotted(self, fake_project: Path) -> None:
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")
        (fake_project / SERVICE_FILE).write_text("my local edit\n")

        updater.install_plugin_template_tree(
            "aegis_plugin_test", backup_label="test_plugin/0.0.1"
        )

        backup = fake_project / ".aegis/plugin-backups/test_plugin/0.0.1" / SERVICE_FILE
        assert backup.is_file(), "replaced local edit was not snapshotted"
        assert backup.read_text() == "my local edit\n"

    def test_reports_which_files_were_replaced(self, fake_project: Path) -> None:
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")
        (fake_project / SERVICE_FILE).write_text("my local edit\n")

        result = updater.render_plugin_tree(
            "aegis_plugin_test", backup_label="test_plugin/0.0.1"
        )

        assert SERVICE_FILE in result.replaced
        # The untouched sibling was re-rendered identically, so it is not
        # reported as replaced.
        assert "app/services/test_plugin/__init__.py" not in result.replaced

    def test_backup_label_defaults_when_version_unknown(
        self, fake_project: Path
    ) -> None:
        updater = ManualUpdater(fake_project)
        updater.install_plugin_template_tree("aegis_plugin_test")
        (fake_project / SERVICE_FILE).write_text("my local edit\n")

        updater.install_plugin_template_tree("aegis_plugin_test")

        backup = fake_project / ".aegis/plugin-backups/previous" / SERVICE_FILE
        assert backup.is_file()
        assert backup.read_text() == "my local edit\n"


class TestBackupLabelSegmentsArePathSafe:
    """The backup directory is built from a plugin's ``spec.name`` and the
    version recorded in ``.copier-answers.yml``. Neither is validated on
    the install path — ``validate_plugin_name`` only guards
    ``aegis plugins create`` — and the answers file is user-editable, so a
    stray separator would put the snapshot outside the backup directory.
    """

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../etc",
            "a/b",
            "scraper/../../..",
            "..",
            ".",
            "...",
            "",
            "/",
            "..\\..\\windows",
            "1.0/rc1",
        ],
    )
    def test_result_can_never_escape_the_backup_directory(self, hostile: str) -> None:
        """The property that matters, asserted instead of the exact
        sanitized spelling: whatever comes out, joining it under the
        backup root must stay under the backup root."""
        root = Path("/tmp/backups").resolve()
        joined = (root / _safe_path_segment(hostile)).resolve()

        assert joined != root, f"{hostile!r} collapsed onto the root itself"
        assert joined.parent == root, f"{hostile!r} escaped to {joined}"

    def test_ordinary_names_and_versions_pass_through_unchanged(self) -> None:
        """Sanitizing must not mangle the normal case — the overwhelming
        majority — or backup paths stop being recognizable."""
        for ordinary in ("scraper", "metrics_hub", "1.2.0", "2.0.0-rc1"):
            assert _safe_path_segment(ordinary) == ordinary
