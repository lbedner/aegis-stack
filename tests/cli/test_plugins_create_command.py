"""
Tests for ``aegis plugins create`` (#774).

The scaffolder itself is unit-tested in
``tests/core/test_plugin_scaffold.py``. These tests cover the CLI
surface: argument validation, confirmation prompt, and the success
banner that points the user at next steps.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from aegis.commands.plugins import plugins_app

runner = CliRunner()


class TestArgValidation:
    def test_invalid_name_errors(self, tmp_path: Path) -> None:
        result = runner.invoke(
            plugins_app,
            ["create", "Stripe", "--target-dir", str(tmp_path), "--yes"],
        )
        assert result.exit_code == 1
        assert "must be lowercase" in result.output

    def test_missing_target_dir_errors(self, tmp_path: Path) -> None:
        nope = tmp_path / "missing"
        result = runner.invoke(
            plugins_app,
            ["create", "scraper", "--target-dir", str(nope), "--yes"],
        )
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_existing_output_dir_errors(self, tmp_path: Path) -> None:
        (tmp_path / "aegis-stack-scraper").mkdir()
        result = runner.invoke(
            plugins_app,
            ["create", "scraper", "--target-dir", str(tmp_path), "--yes"],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestSuccessFlow:
    def test_creates_scaffold(self, tmp_path: Path) -> None:
        result = runner.invoke(
            plugins_app,
            [
                "create",
                "scraper",
                "--target-dir",
                str(tmp_path),
                "--author",
                "Demo Dev",
                "--description",
                "Demo plugin",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "Created" in result.output
        assert "Next steps:" in result.output
        # Spot-check that the scaffold actually landed.
        assert (tmp_path / "aegis-stack-scraper" / "pyproject.toml").is_file()

    def test_next_steps_name_the_file_that_was_created(self, tmp_path: Path) -> None:
        """The edit hint used to print ``src/aegis_stack_<name>/plugin.py``
        with the placeholder never filled in."""
        result = runner.invoke(
            plugins_app,
            ["create", "scraper", "--target-dir", str(tmp_path), "--yes"],
        )
        assert result.exit_code == 0
        plugin_file = "src/aegis_stack_scraper/plugin.py"
        assert plugin_file in result.output
        assert (tmp_path / "aegis-stack-scraper" / plugin_file).is_file()
        assert "<name>" not in result.output

    def test_cancellation_creates_nothing(self, tmp_path: Path) -> None:
        # No --yes; simulate the user typing 'n' at the prompt.
        result = runner.invoke(
            plugins_app,
            ["create", "scraper", "--target-dir", str(tmp_path)],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Cancelled" in result.output
        assert not (tmp_path / "aegis-stack-scraper").exists()
