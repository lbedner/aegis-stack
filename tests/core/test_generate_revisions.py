"""``generate_revisions`` runs the project's own generator, in its venv."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from aegis.core.migration_generator import (
    MigrationGenerationError,
    generate_revisions,
)


def _versions(tmp_path: Path) -> Path:
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    return versions


def test_runs_migrate_gen_in_the_project_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UV_PYTHON", "3.11")
    versions = _versions(tmp_path)

    def fake_run(cmd: list[str], **_kw: object) -> Mock:
        (versions / "001_auth.py").write_text("")
        return Mock(returncode=0, stderr="", stdout="001_auth.py\n")

    with patch(
        "aegis.core.migration_generator.subprocess.run", side_effect=fake_run
    ) as run:
        written = generate_revisions(
            tmp_path, ["auth", "finance"], python_version="3.13"
        )

    cmd = run.call_args.args[0]
    assert cmd[:4] == ["uv", "run", "--project", str(tmp_path)]
    assert "--python" in cmd and cmd[cmd.index("--python") + 1] == "3.13"
    assert cmd[-5:] == ["python", "-m", "app.cli.migrate_gen", "auth", "finance"]
    env = run.call_args.kwargs["env"]
    assert "VIRTUAL_ENV" not in env
    # the tool's own interpreter pin must not reach the project's resolve
    assert "UV_PYTHON" not in env
    assert written == [versions / "001_auth.py"]


def test_returns_only_files_this_call_wrote(tmp_path: Path) -> None:
    versions = _versions(tmp_path)
    (versions / "001_auth.py").write_text("")

    def fake_run(cmd: list[str], **_kw: object) -> Mock:
        (versions / "002_blog.py").write_text("")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("aegis.core.migration_generator.subprocess.run", side_effect=fake_run):
        assert generate_revisions(tmp_path, ["blog"]) == [versions / "002_blog.py"]


def test_no_services_runs_nothing(tmp_path: Path) -> None:
    with patch("aegis.core.migration_generator.subprocess.run") as run:
        assert generate_revisions(tmp_path, []) == []
    run.assert_not_called()


def test_failure_raises_with_the_generator_output(tmp_path: Path) -> None:
    _versions(tmp_path)
    with (
        patch(
            "aegis.core.migration_generator.subprocess.run",
            return_value=Mock(
                returncode=1, stderr="ImportError: no module named plaid", stdout=""
            ),
        ),
        pytest.raises(MigrationGenerationError, match="plaid"),
    ):
        generate_revisions(tmp_path, ["finance"])


def test_alembic_pin_matches_the_template(tmp_path: Path) -> None:
    """``_pin_alembic`` writes what a rendered project would have pinned."""
    from aegis.core.migration_generator import ALEMBIC_PIN

    template = Path("aegis/templates/copier-aegis-project/{{ project_slug }}")
    assert f'"{ALEMBIC_PIN}"' in (template / "pyproject.toml.jinja").read_text()


def test_bootstrap_pins_alembic_once(tmp_path: Path) -> None:
    from aegis.core.migration_generator import ALEMBIC_PIN, _pin_alembic

    pyproject = tmp_path / "pyproject.toml"
    # Every database project names alembic in its poe tasks; only the
    # dependency list decides whether it is installed.
    pyproject.write_text(
        '[project]\ndependencies = [\n    "fastapi",\n]\n'
        '\n[tool.poe.tasks.migrate]\ncmd = "uv run alembic upgrade head"\n'
    )
    _pin_alembic(tmp_path)
    _pin_alembic(tmp_path)
    assert pyproject.read_text().count(ALEMBIC_PIN) == 1


class TestDataStatements:
    """``ServiceMigrationSpec.data_sql`` (#1110): the one thing the models
    can never derive. ``generate_revisions`` appends it to the revision it
    wrote for the service - or, when the models produced nothing for that
    service (``finance_auth_link``: its FKs are inline in ``finance`` now),
    writes a data-only revision so the statement still has a home."""

    SENTINEL = "standalone@finance.local"

    def test_appended_to_the_revision_the_service_wrote(self, tmp_path: Path) -> None:
        versions = _versions(tmp_path)

        def fake_run(cmd: list[str], **_kw: object) -> Mock:
            (versions / "001_finance_auth_link.py").write_text(
                "from alembic import op\n\n\ndef upgrade() -> None:\n    pass\n\n\n"
                "def downgrade() -> None:\n    pass\n"
            )
            return Mock(returncode=0, stderr="", stdout="")

        with patch(
            "aegis.core.migration_generator.subprocess.run", side_effect=fake_run
        ):
            written = generate_revisions(tmp_path, ["finance_auth_link"])

        assert written == [versions / "001_finance_auth_link.py"]
        src = written[0].read_text()
        assert self.SENTINEL in src
        assert src.index(self.SENTINEL) < src.index("def downgrade")

    def test_data_only_revision_when_the_models_wrote_nothing(
        self, tmp_path: Path
    ) -> None:
        versions = _versions(tmp_path)
        (versions / "001_auth.py").write_text("")
        (versions / "002_finance.py").write_text("")

        with patch(
            "aegis.core.migration_generator.subprocess.run",
            return_value=Mock(returncode=0, stderr="", stdout=""),
        ):
            written = generate_revisions(tmp_path, ["finance_auth_link"])

        assert written == [versions / "003_finance_auth_link.py"]
        src = written[0].read_text()
        assert "revision = '003'" in src
        assert "down_revision = '002'" in src
        assert self.SENTINEL in src
        assert "def downgrade" in src

    def test_data_only_revision_is_written_once(self, tmp_path: Path) -> None:
        versions = _versions(tmp_path)
        (versions / "001_finance_auth_link.py").write_text("")

        with patch(
            "aegis.core.migration_generator.subprocess.run",
            return_value=Mock(returncode=0, stderr="", stdout=""),
        ):
            assert generate_revisions(tmp_path, ["finance_auth_link"]) == []

    def test_services_without_data_are_untouched(self, tmp_path: Path) -> None:
        versions = _versions(tmp_path)

        with patch(
            "aegis.core.migration_generator.subprocess.run",
            return_value=Mock(returncode=0, stderr="", stdout=""),
        ):
            assert generate_revisions(tmp_path, ["blog"]) == []
        assert list(versions.glob("*.py")) == []


class TestScratchReplayFailure:
    """A revision that needs data dies replaying onto the empty scratch database.

    All the operator gets today is the traceback tail, which ends in the
    migration's own message — nothing says which revision, that the database
    was a scratch one, or that the fix is to tolerate an empty database.
    """

    TRACEBACK = (
        "Traceback (most recent call last):\n"
        '  File "/app/.venv/lib/python3.13/site-packages/alembic/runtime/migration.py"'
        ", line 623, in run_migrations\n"
        "    step.migration_fn(**kw)\n"
        '  File "/app/alembic/versions/009_seed_projects.py", line 41, in upgrade\n'
        "    owner = conn.execute(select(User)).one()\n"
        "sqlalchemy.exc.NoResultFound: No row was found when one was required\n"
    )

    def _error(self, tmp_path: Path, stderr: str) -> str:
        _versions(tmp_path)
        with (
            patch(
                "aegis.core.migration_generator.subprocess.run",
                return_value=Mock(returncode=1, stderr=stderr, stdout=""),
            ),
            pytest.raises(MigrationGenerationError) as caught,
        ):
            generate_revisions(tmp_path, ["insights"])
        return str(caught.value)

    def test_names_the_revision_and_the_scratch_database(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, self.TRACEBACK)
        assert "009_seed_projects.py" in message
        assert "scratch" in message
        # Last word, so it survives a tail read and is not buried in traceback.
        assert message.rstrip().endswith("empty database.")

    def test_unrelated_failure_is_left_alone(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, "ImportError: no module named plaid")
        assert "plaid" in message
        assert "scratch" not in message
