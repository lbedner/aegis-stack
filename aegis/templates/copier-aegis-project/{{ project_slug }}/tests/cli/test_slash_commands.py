"""Tests for slash command handler."""

from io import StringIO
from unittest.mock import MagicMock

import pytest
from app.cli.slash_commands import SlashCommandHandler
from app.cli.status_line import ChatSessionState
from rich.console import Console


@pytest.fixture
def mock_ai_service() -> MagicMock:
    """Mock AIService for slash command handler."""
    service = MagicMock()
    service.config.provider.value = "openai"
    service.config.model = "gpt-4o"
    service.config.temperature = 0.7
    service.config.max_tokens = 4096
    return service


@pytest.fixture
def mock_console() -> Console:
    """Console with StringIO for output capture."""
    output = StringIO()
    return Console(file=output, force_terminal=False, width=80)


@pytest.fixture
def command_handler(
    mock_ai_service: MagicMock, mock_console: Console
) -> SlashCommandHandler:
    """SlashCommandHandler with mocks and pre-populated cache."""
    session_state = ChatSessionState(provider="openai", model="gpt-4o")
    # ``rag_enabled`` / ``rag_collection`` were refactored out of the
    # ``SlashCommandHandler`` constructor — RAG state now lives on the
    # ``ChatSessionState`` or the handler's mutable attrs. Tests that
    # need to toggle RAG state do so by assigning to ``handler.rag_enabled``
    # / ``handler.rag_collection`` after construction (see below).
    handler = SlashCommandHandler(
        ai_service=mock_ai_service,
        session_state=session_state,
        console=mock_console,
    )
    handler._collection_cache = ["my-code", "docs", "tests"]
    handler._model_cache = ["gpt-4o", "gpt-4-turbo", "claude-sonnet-4"]
    return handler


class TestSlashCommandParsing:
    """Test command detection and parsing."""

    def test_is_slash_command_with_slash(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Text starting with / is a slash command."""
        assert command_handler.is_slash_command("/help") is True
        assert command_handler.is_slash_command("/model gpt-4o") is True

    def test_is_slash_command_without_slash(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Regular text is not a slash command."""
        assert command_handler.is_slash_command("hello") is False
        assert command_handler.is_slash_command("help") is False

    def test_is_slash_command_with_whitespace(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Whitespace before / still detected."""
        assert command_handler.is_slash_command("  /help") is True
        assert command_handler.is_slash_command("\t/model") is True

    def test_parse_input_simple_command(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Parse /help returns ('help', [])."""
        cmd, args = command_handler.parse_input("/help")
        assert cmd == "help"
        assert args == []

    def test_parse_input_with_args(self, command_handler: SlashCommandHandler) -> None:
        """Parse /model gpt-4o returns ('model', ['gpt-4o'])."""
        cmd, args = command_handler.parse_input("/model gpt-4o")
        assert cmd == "model"
        assert args == ["gpt-4o"]

    def test_parse_input_case_insensitive(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Commands are lowercased."""
        cmd, args = command_handler.parse_input("/HELP")
        assert cmd == "help"

        cmd, args = command_handler.parse_input("/Model GPT-4o")
        assert cmd == "model"

    def test_parse_input_non_slash(self, command_handler: SlashCommandHandler) -> None:
        """Non-slash input returns (None, [])."""
        cmd, args = command_handler.parse_input("hello world")
        assert cmd is None
        assert args == []


class TestCommandNames:
    """Test command name retrieval."""

    def test_get_command_names_includes_all_commands(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """All registered commands returned.

        ``/rag`` was removed when RAG state moved off the slash-command
        handler and onto ``ChatSessionState``; it's no longer a
        registered command. See ``TestCmdRag`` (skipped below).
        """
        names = command_handler.get_command_names()
        assert "help" in names
        assert "clear" in names
        assert "new" in names
        assert "model" in names
        assert "status" in names
        assert "exit" in names

    def test_get_command_names_sorted(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Names returned in sorted order."""
        names = command_handler.get_command_names()
        assert names == sorted(names)

    def test_get_model_completions_returns_cache(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Model completions come from cache."""
        completions = command_handler.get_model_completions()
        assert completions == ["gpt-4o", "gpt-4-turbo", "claude-sonnet-4"]

    def test_get_collection_completions_returns_cache(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Collection completions come from cache."""
        completions = command_handler.get_collection_completions()
        assert completions == ["my-code", "docs", "tests"]


class TestCmdNew:
    """Test /new command."""

    @pytest.mark.asyncio
    async def test_new_resets_conversation_id(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """New command sets new_conversation_id='new'."""
        command_handler.current_conversation_id = "existing-123"

        result = await command_handler.execute("/new")

        assert result is not None
        assert result.success is True
        assert result.new_conversation_id == "new"

    @pytest.mark.asyncio
    async def test_new_clears_handler_conversation_id(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Handler's current_conversation_id set to None."""
        command_handler.current_conversation_id = "existing-123"

        await command_handler.execute("/new")

        assert command_handler.current_conversation_id is None


@pytest.mark.skip(
    reason=(
        "The /rag slash command was removed when RAG state moved off "
        "``SlashCommandHandler`` onto ``ChatSessionState``. These tests "
        "exercise a command that no longer exists and should be "
        "rewritten against the new RAG-state API before un-skipping."
    )
)
class TestCmdRag:
    """Test /rag command variations."""

    @pytest.mark.asyncio
    async def test_rag_no_args_shows_status_panel(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """No args shows status panel with current state."""
        result = await command_handler.execute("/rag")

        assert result is not None
        assert result.success is True
        # No updates when just showing status
        assert result.update_rag is None

    @pytest.mark.asyncio
    async def test_rag_off_disables(self, command_handler: SlashCommandHandler) -> None:
        """'/rag off' returns update_rag=False."""
        command_handler.rag_enabled = True

        result = await command_handler.execute("/rag off")

        assert result is not None
        assert result.success is True
        assert result.update_rag is False

    @pytest.mark.asyncio
    async def test_rag_collection_name_switches(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """'/rag my-code' enables RAG with that collection."""
        result = await command_handler.execute("/rag my-code")

        assert result is not None
        assert result.success is True
        assert result.update_rag is True
        assert result.update_rag_collection == "my-code"

    @pytest.mark.asyncio
    async def test_rag_invalid_collection_returns_error(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Unknown collection returns success=False."""
        result = await command_handler.execute("/rag nonexistent")

        assert result is not None
        assert result.success is False
        assert "not found" in (result.message or "").lower()


class TestCmdHelp:
    """Test /help command."""

    @pytest.mark.asyncio
    async def test_help_succeeds(self, command_handler: SlashCommandHandler) -> None:
        """Help command executes successfully."""
        result = await command_handler.execute("/help")

        assert result is not None
        assert result.success is True


class TestCmdExit:
    """Test /exit command."""

    @pytest.mark.asyncio
    async def test_exit_returns_should_exit(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Exit command sets should_exit=True."""
        result = await command_handler.execute("/exit")

        assert result is not None
        assert result.success is True
        assert result.should_exit is True


class TestUnknownCommand:
    """Test handling of unknown commands."""

    @pytest.mark.asyncio
    async def test_unknown_command_fails(
        self, command_handler: SlashCommandHandler
    ) -> None:
        """Unknown command returns success=False."""
        result = await command_handler.execute("/unknown")

        assert result is not None
        assert result.success is False
        assert "unknown" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_model_refused_for_an_unkeyed_provider_stays_refused(
    command_handler: SlashCommandHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A catalog model whose provider has no key is not forced through, and
    the command says why instead of claiming a switch."""
    llm_service = pytest.importorskip(
        "app.services.ai.domains.llm.llm_service", reason="no catalog"
    )

    calls: list[bool] = []

    async def refuse(model_id: str, force: bool = False) -> llm_service.SetModelResult:
        calls.append(force)
        return llm_service.SetModelResult(
            success=False,
            model_id=model_id,
            vendor="openai",
            provider_updated=False,
            message="OpenAI has no API key. Set OPENAI_API_KEY in .env first.",
        )

    monkeypatch.setattr(llm_service, "set_active_model", refuse)
    result = await command_handler._cmd_model(["gpt-6-luna"])
    assert calls == [False]
    assert result.success is False
    assert "OPENAI_API_KEY" in (result.message or "")
