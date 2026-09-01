"""Tests for LLM catalog CLI commands."""

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from app.cli.main import app
from app.services.ai.domains.llm.etl.llm_sync_service import SyncResult
from app.services.ai.domains.llm.llm_service import ModalityListResult, VendorListResult

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI styling from CLI output.

    Typer's themed ``--help`` highlights a flag like ``--mode`` as two
    overlapping spans (the ``--mode`` option and the ``-mode`` switch),
    so the colorized bytes carry a reset between the dashes and the literal
    ``--mode`` substring is absent. Stripping ANSI lets flag assertions
    check the rendered text rather than its presentation.
    """
    return _ANSI_RE.sub("", text)


class TestLLMOrgsCommand:
    """Tests for the 'llm vendors' command."""

    def test_vendors_help(self) -> None:
        """Test that vendors help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "vendors", "--help"])
        assert result.exit_code == 0
        assert "List all LLM vendors" in result.output

    @patch("app.cli.llm.list_vendors")
    def test_vendors_empty_catalog(self, mock_list_vendors) -> None:
        """Test vendors command with empty catalog."""
        mock_list_vendors.return_value = []

        result = runner.invoke(app, ["llm", "vendors"])

        assert result.exit_code == 0
        assert "No vendors found" in result.output
        assert "llm sync" in result.output

    @patch("app.cli.llm.list_vendors")
    def test_vendors_with_data(self, mock_list_vendors) -> None:
        """Test vendors command with vendor data."""
        mock_list_vendors.return_value = [
            VendorListResult(name="anthropic", model_count=22),
            VendorListResult(name="openai", model_count=15),
        ]

        result = runner.invoke(app, ["llm", "vendors"])

        assert result.exit_code == 0
        assert "anthropic" in result.output
        assert "22" in result.output
        assert "openai" in result.output
        assert "15" in result.output
        assert "2 total" in result.output


class TestLLMModalitiesCommand:
    """Tests for the 'llm modalities' command."""

    def test_modalities_help(self) -> None:
        """Test that modalities help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "modalities", "--help"])
        assert result.exit_code == 0
        assert "List all modalities" in result.output

    @patch("app.cli.llm.list_modalities")
    def test_modalities_empty_catalog(self, mock_list_modalities) -> None:
        """Test modalities command with empty catalog."""
        mock_list_modalities.return_value = []

        result = runner.invoke(app, ["llm", "modalities"])

        assert result.exit_code == 0
        assert "No modalities found" in result.output
        assert "llm sync" in result.output

    @patch("app.cli.llm.list_modalities")
    def test_modalities_with_data(self, mock_list_modalities) -> None:
        """Test modalities command with modality data."""
        mock_list_modalities.return_value = [
            ModalityListResult(modality="audio", model_count=72),
            ModalityListResult(modality="image", model_count=451),
            ModalityListResult(modality="text", model_count=1748),
            ModalityListResult(modality="video", model_count=10),
        ]

        result = runner.invoke(app, ["llm", "modalities"])

        assert result.exit_code == 0
        assert "audio" in result.output
        assert "72" in result.output
        assert "text" in result.output
        assert "1748" in result.output
        # Rich table may wrap "(4 total)" across lines
        assert "4" in result.output and "total" in result.output


class TestLLMStatusCommand:
    """Tests for the 'llm status' command."""

    def test_status_help(self) -> None:
        """Test that status help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "status", "--help"])
        assert result.exit_code == 0
        assert "Show LLM catalog statistics" in result.output


class TestLLMSyncCommand:
    """Tests for the 'llm sync' command."""

    def test_sync_help(self) -> None:
        """Test that sync help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "sync", "--help"])
        assert result.exit_code == 0
        assert "Sync LLM catalog" in result.output
        plain = _plain(result.output)
        assert "--mode" in plain
        assert "--dry-run" in plain
        assert "--refresh" in plain

    def test_sync_source_flag_in_help(self) -> None:
        """Test that --source flag appears in help text."""
        result = runner.invoke(app, ["llm", "sync", "--help"])
        assert result.exit_code == 0
        plain = _plain(result.output)
        assert "--source" in plain
        assert "cloud" in plain
        assert "ollama" in plain

    @patch("app.cli.llm.sync_llm_catalog")
    @patch("app.cli.llm.Session")
    @patch("app.cli.llm.engine")
    def test_sync_source_ollama(
        self,
        mock_engine: MagicMock,
        mock_session_class: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Test that --source=ollama passes correct parameter."""
        # Setup mocks
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_class.return_value = mock_session

        mock_sync.return_value = SyncResult(
            vendors_added=1,
            models_added=2,
        )

        result = runner.invoke(app, ["llm", "sync", "--source=ollama"])

        assert result.exit_code == 0
        # Verify sync was called with source="ollama"
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        # asyncio.run wraps the coroutine, so check the positional/keyword args
        assert call_kwargs[1].get("source") == "ollama"

    @patch("app.cli.llm.sync_llm_catalog")
    @patch("app.cli.llm.Session")
    @patch("app.cli.llm.engine")
    def test_sync_source_cloud(
        self,
        mock_engine: MagicMock,
        mock_session_class: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Test that --source=cloud passes correct parameter."""
        # Setup mocks
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_class.return_value = mock_session

        mock_sync.return_value = SyncResult(
            vendors_added=5,
            models_added=100,
        )

        result = runner.invoke(app, ["llm", "sync", "--source=cloud"])

        assert result.exit_code == 0
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        assert call_kwargs[1].get("source") == "cloud"

    @patch("app.cli.llm.sync_llm_catalog")
    @patch("app.cli.llm.Session")
    @patch("app.cli.llm.engine")
    def test_sync_source_all(
        self,
        mock_engine: MagicMock,
        mock_session_class: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Test that --source=all passes correct parameter."""
        # Setup mocks
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_class.return_value = mock_session

        mock_sync.return_value = SyncResult(
            vendors_added=6,
            models_added=102,
        )

        result = runner.invoke(app, ["llm", "sync", "--source=all"])

        assert result.exit_code == 0
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        assert call_kwargs[1].get("source") == "all"

    @patch("app.cli.llm.sync_llm_catalog")
    @patch("app.cli.llm.Session")
    @patch("app.cli.llm.engine")
    def test_sync_default_source_is_cloud(
        self,
        mock_engine: MagicMock,
        mock_session_class: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Test that default source is 'cloud' when not specified."""
        # Setup mocks
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_class.return_value = mock_session

        mock_sync.return_value = SyncResult()

        result = runner.invoke(app, ["llm", "sync"])

        assert result.exit_code == 0
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        # Default should be "cloud"
        assert call_kwargs[1].get("source") == "cloud"

    @patch("app.cli.llm.sync_llm_catalog")
    @patch("app.cli.llm.Session")
    @patch("app.cli.llm.engine")
    def test_sync_source_short_flag(
        self,
        mock_engine: MagicMock,
        mock_session_class: MagicMock,
        mock_sync: MagicMock,
    ) -> None:
        """Test that -s short flag works for source."""
        # Setup mocks
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_class.return_value = mock_session

        mock_sync.return_value = SyncResult(
            vendors_added=1,
            models_added=2,
        )

        result = runner.invoke(app, ["llm", "sync", "-s", "ollama"])

        assert result.exit_code == 0
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        assert call_kwargs[1].get("source") == "ollama"


class TestLLMListCommand:
    """Tests for the 'llm list' command."""

    def test_list_help(self) -> None:
        """Test that list help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "list", "--help"])
        assert result.exit_code == 0
        assert "List LLM models" in result.output
        plain = _plain(result.output)
        assert "--vendor" in plain
        assert "--modality" in plain


class TestLLMUseCommand:
    """Tests for the 'llm use' command."""

    def test_use_help(self) -> None:
        """Test that use help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "use", "--help"])
        assert result.exit_code == 0
        assert "Switch to a different LLM model" in result.output
        assert "--force" in _plain(result.output)


class TestLLMInfoCommand:
    """Tests for the 'llm info' command."""

    def test_info_help(self) -> None:
        """Test that info help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "info", "--help"])
        assert result.exit_code == 0
        assert "Show detailed information" in result.output


class TestLLMCurrentCommand:
    """Tests for the 'llm current' command."""

    def test_current_help(self) -> None:
        """Test that current help text is displayed correctly."""
        result = runner.invoke(app, ["llm", "current", "--help"])
        assert result.exit_code == 0
        assert "Show current LLM configuration" in result.output
