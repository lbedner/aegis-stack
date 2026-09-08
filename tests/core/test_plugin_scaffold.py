"""
Tests for ``aegis.core.plugin_scaffold`` (#774).

The scaffolder renders the templates under
``aegis/templates/plugin_scaffold/`` into a fresh ``aegis-stack-<name>``
directory. Tests verify file layout, content substitution, and the
errors the CLI surfaces for invalid input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core.plugins.scaffold import scaffold_plugin, validate_plugin_name


class TestValidateName:
    @pytest.mark.parametrize("name", ["scraper", "stripe", "metrics_hub", "ai_search"])
    def test_accepts_valid(self, name: str) -> None:
        validate_plugin_name(name)  # should not raise

    @pytest.mark.parametrize(
        "name",
        [
            "Scraper",  # uppercase
            "1plugin",  # leading digit
            "stripe-payments",  # hyphen
            "stripe payments",  # space
            "stripe.payments",  # dot
            "",  # empty
        ],
    )
    def test_rejects_invalid(self, name: str) -> None:
        with pytest.raises(ValueError):
            validate_plugin_name(name)


class TestScaffoldStructure:
    def test_creates_expected_files(self, tmp_path: Path) -> None:
        scaffold_plugin("scraper", tmp_path, author="Tester")

        root = tmp_path / "aegis-stack-scraper"
        assert root.is_dir()
        # Expected files (pin the layout — easier to spot regressions
        # than enumerating "at least these"):
        expected = {
            "pyproject.toml",
            "README.md",
            "Makefile",
            ".gitignore",
            ".pre-commit-config.yaml",
            ".github/workflows/test.yml",
            "src/aegis_stack_scraper/__init__.py",
            "src/aegis_stack_scraper/plugin.py",
            (
                "src/aegis_stack_scraper/templates/{{ project_slug }}/"
                "app/services/scraper/__init__.py"
            ),
            "tests/__init__.py",
            "tests/test_plugin.py",
        }
        actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert actual == expected

    def test_pluginpkg_placeholder_substituted_in_path(self, tmp_path: Path) -> None:
        scaffold_plugin("metrics_hub", tmp_path)
        pkg_dir = (
            tmp_path / "aegis-stack-metrics_hub" / "src" / "aegis_stack_metrics_hub"
        )
        assert pkg_dir.is_dir()

    def test_project_slug_directory_kept_literal(self, tmp_path: Path) -> None:
        """Plugin authors expect the rendered tree to contain a literal
        ``{{ project_slug }}/`` directory — that's what
        ``plugin_template_resolver`` walks. Substituting it at scaffold
        time would break the convention."""
        scaffold_plugin("scraper", tmp_path)
        target = (
            tmp_path
            / "aegis-stack-scraper"
            / "src"
            / "aegis_stack_scraper"
            / "templates"
            / "{{ project_slug }}"
        )
        assert target.is_dir()


class TestScaffoldContent:
    def test_pyproject_has_entry_point_for_aegis_plugins(self, tmp_path: Path) -> None:
        scaffold_plugin("scraper", tmp_path, author="Demo Dev")
        pyproject = (tmp_path / "aegis-stack-scraper" / "pyproject.toml").read_text()
        assert 'name = "aegis-stack-scraper"' in pyproject
        assert 'authors = [{ name = "Demo Dev" }]' in pyproject
        assert '[project.entry-points."aegis.plugins"]' in pyproject
        assert 'scraper = "aegis_stack_scraper.plugin:get_spec"' in pyproject

    def test_pyproject_requires_python_matches_aegis_stack_floor(
        self, tmp_path: Path
    ) -> None:
        """Plugin scaffold's ``requires-python`` floor must match
        aegis-stack's own (``>=3.11``). A ``>=3.10`` claim would let
        ``pip install aegis-stack-X`` accept Python 3.10 while the
        aegis-stack dependency itself rejects it — the failure surfaces
        at install time with a confusing message."""
        scaffold_plugin("scraper", tmp_path)
        pyproject = (tmp_path / "aegis-stack-scraper" / "pyproject.toml").read_text()
        assert 'requires-python = ">=3.11"' in pyproject

    def test_plugin_py_returns_valid_pluginspec(self, tmp_path: Path) -> None:
        scaffold_plugin("scraper", tmp_path, description="Web scraping")
        plugin_py = (
            tmp_path
            / "aegis-stack-scraper"
            / "src"
            / "aegis_stack_scraper"
            / "plugin.py"
        ).read_text()
        assert "def get_spec()" in plugin_py
        assert 'name="scraper"' in plugin_py
        assert "PluginKind.SERVICE" in plugin_py
        assert 'description="Web scraping"' in plugin_py

    def test_test_file_imports_get_spec(self, tmp_path: Path) -> None:
        scaffold_plugin("scraper", tmp_path)
        test_py = (
            tmp_path / "aegis-stack-scraper" / "tests" / "test_plugin.py"
        ).read_text()
        assert "from aegis_stack_scraper.plugin import get_spec" in test_py


class TestScaffoldErrors:
    def test_target_dir_must_exist(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        with pytest.raises(FileNotFoundError):
            scaffold_plugin("scraper", missing)

    def test_existing_output_rejected(self, tmp_path: Path) -> None:
        scaffold_plugin("scraper", tmp_path)
        with pytest.raises(FileExistsError):
            scaffold_plugin("scraper", tmp_path)

    def test_invalid_name_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            scaffold_plugin("Stripe", tmp_path)


class TestScaffoldedPluginIsImportable:
    """The ultimate smoke test: a freshly scaffolded plugin's
    ``get_spec()`` should import + return a ``PluginSpec`` without
    needing any author edits. Pip-install would normally bridge this,
    but for the unit test we exec the rendered ``plugin.py`` directly."""

    def test_get_spec_runs_with_valid_pluginspec(self, tmp_path: Path) -> None:
        from aegis.core.plugins.spec import PluginKind, PluginSpec

        scaffold_plugin("scraper", tmp_path)
        plugin_py = (
            tmp_path
            / "aegis-stack-scraper"
            / "src"
            / "aegis_stack_scraper"
            / "plugin.py"
        ).read_text()

        # Exec in an isolated namespace; the rendered file's only
        # external imports are aegis core modules already importable.
        ns: dict = {}
        exec(plugin_py, ns)  # noqa: S102 — controlled internal content
        spec = ns["get_spec"]()
        assert isinstance(spec, PluginSpec)
        assert spec.name == "scraper"
        assert spec.kind == PluginKind.SERVICE


class TestDiscoveryMetadata:
    """The plugin directory on aegis-stack.io finds candidates from PyPI
    core metadata (keywords, project URLs) and proves them by reading the
    ``aegis.plugins`` entry point out of the wheel. The scaffold emits the
    markers so authors never think about them."""

    def test_pyproject_carries_keywords_and_marker_url(self, tmp_path: Path) -> None:
        import tomllib

        scaffold_plugin("scraper", tmp_path, author="Tester")
        project = tomllib.loads(
            (tmp_path / "aegis-stack-scraper" / "pyproject.toml").read_text()
        )["project"]
        assert "aegis-stack-plugin" in project["keywords"]
        assert project["urls"]["Aegis Plugin"] == (
            "https://aegis-stack.io/plugins/aegis-stack-scraper"
        )

    def test_readme_points_at_the_plugin_docs(self, tmp_path: Path) -> None:
        """The README does not repeat how listing works; it links the page
        that owns that explanation."""
        scaffold_plugin("scraper", tmp_path, author="Tester")
        readme = (tmp_path / "aegis-stack-scraper" / "README.md").read_text()
        assert "https://docs.aegis-stack.io/plugins/" in readme


class TestWheelRoundTrip:
    def test_built_wheel_declares_the_entry_point(self, tmp_path: Path) -> None:
        """Exactly the check the directory performs: build the scaffold into
        a wheel and read ``entry_points.txt`` back out of the zip."""
        import configparser
        import subprocess
        import zipfile

        scaffold_plugin("scraper", tmp_path, author="Tester")
        root = tmp_path / "aegis-stack-scraper"
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        (wheel,) = (tmp_path / "dist").glob("*.whl")
        with zipfile.ZipFile(wheel) as zf:
            (entry_points_file,) = (
                n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")
            )
            text = zf.read(entry_points_file).decode()
        parser = configparser.ConfigParser()
        parser.read_string(text)
        assert (
            parser["aegis.plugins"]["scraper"] == "aegis_stack_scraper.plugin:get_spec"
        )
