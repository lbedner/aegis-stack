"""The interactive chat loop: the REPL behind ``ai chat``."""

import asyncio
import os
import shutil

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich.panel import Panel

from app.cli import theme
from app.cli.ai.shared import _use_streaming, get_provider_display_name
from app.cli.ai.streaming import _stream_chat_response
from app.cli.chat_completer import ChatCompleter
from app.cli.slash_commands import SlashCommandHandler
from app.cli.status_line import ChatSessionState, create_toolbar_callback
from app.i18n import t

from ...core.config import settings
from ...services.ai.config import get_ai_config
from ...services.ai.domains.llm.providers import ProviderNotInstalledError

console = theme.console()


async def _interactive_chat_session(
    ai_service,
    conversation_id: str | None = None,
) -> None:
    """Start an interactive chat session with continuous conversation."""

    from app import __aegis_version__

    # Illiana boot sequence
    ai_config = get_ai_config(settings)

    console.print()
    banner = (
        f"[bold {theme.ACCENT}]Illiana[/bold {theme.ACCENT}] "
        f"[dim]v{__aegis_version__}[/dim]"
    )
    console.print(banner)
    console.print()

    # Boot steps with brief delays for effect
    console.print(f"  [dim]>[/dim] {t('ai.initializing')}", end="")
    await asyncio.sleep(0.15)
    console.print(f" [{theme.ACCENT}]{t('ai.ok')}[/{theme.ACCENT}]")

    provider_name = get_provider_display_name(ai_config.provider)
    connecting_label = t("ai.connecting_to", provider=provider_name)
    console.print(
        f"  [dim]>[/dim] {connecting_label}",
        end="",
    )
    # Warm up the agent (lazy imports, model initialization)
    from app.services.ai.domains.llm.providers import get_agent

    _ = get_agent(ai_config, settings)
    console.print(f" [{theme.ACCENT}]{t('ai.ok')}[/{theme.ACCENT}]")

    console.print(f"  [dim]>[/dim] [dim]{t('ai.model_label')}[/dim] {ai_config.model}")

    # Fetch and display health status
    console.print(f"  [dim]>[/dim] {t('ai.health_label')} ", end="")
    try:
        from app.services.system.health import get_system_status

        status = await get_system_status()
        health_pct = status.health_percentage
        if status.overall_healthy:
            console.print(
                f"[{theme.ACCENT}]{t('ai.health_ok', pct=health_pct)}[/{theme.ACCENT}]"
            )
        else:
            unhealthy_count = len(status.unhealthy_components)
            degraded_label = t(
                "ai.health_degraded",
                pct=health_pct,
                count=unhealthy_count,
            )
            console.print(f"[{theme.WARNING}]{degraded_label}[/{theme.WARNING}]")
    except Exception:
        console.print(f"[dim]{t('ai.health_na')}[/dim]")

    await asyncio.sleep(0.1)
    console.print()
    console.print(f"  [bold {theme.ACCENT}]{t('ai.online')}[/bold {theme.ACCENT}]")
    console.print()
    console.print(f"[dim]{t('ai.chat_hints')}[/dim]")
    console.print()

    # Track conversation for context
    current_conversation_id = conversation_id

    # Load cumulative tokens/cost from resumed conversation
    initial_tokens = 0
    initial_cost = 0.0
    if current_conversation_id:
        resumed_conversation = await ai_service.get_conversation(
            current_conversation_id
        )
        if resumed_conversation:
            initial_tokens = resumed_conversation.metadata.get("cumulative_tokens", 0)
            initial_cost = resumed_conversation.metadata.get("cumulative_cost", 0.0)

    # Initialize status line state for prompt_toolkit toolbar
    session_state = ChatSessionState(
        provider=get_provider_display_name(ai_config.provider),
        model=ai_config.model,
        rag_enabled=False,
        rag_collection=None,
        show_sources=False,
        cumulative_tokens=initial_tokens,
        cumulative_cost=initial_cost,
        version=__aegis_version__,
    )
    toolbar_callback = create_toolbar_callback(session_state)

    # Initialize slash command handler for in-session commands
    command_handler = SlashCommandHandler(
        ai_service=ai_service,
        session_state=session_state,
        console=console,
        current_conversation_id=current_conversation_id,
    )

    # Pre-load model cache for tab completion (includes Ollama models)
    await command_handler.load_model_cache()

    # Create completer for slash command autocomplete
    chat_completer = ChatCompleter(command_handler)

    # Create key bindings for common operations
    key_bindings = KeyBindings()

    @key_bindings.add("c-l")
    def _clear_screen(event: object) -> None:
        """Clear screen on Ctrl+L."""
        os.system("cls" if os.name == "nt" else "clear")

    @key_bindings.add("enter")
    def _submit(event: object) -> None:
        """Submit on Enter."""
        event.current_buffer.validate_and_handle()

    @key_bindings.add("escape", "enter")
    def _newline(event: object) -> None:
        """Insert newline on Escape+Enter (or Alt+Enter)."""
        event.current_buffer.insert_text("\n")

    # Create prompt session for async input with status line
    # Style: toolbar blends with terminal, completion menu has dark theme
    prompt_style = Style.from_dict(
        {
            "bottom-toolbar": "noreverse",
            # Dark completion menu styling
            "completion-menu": "bg:#1a1a1a",
            "completion-menu.completion": "fg:#cccccc bg:#1a1a1a",
            "completion-menu.completion.current": "fg:#ffffff bg:#0066cc bold",
            "completion-menu.meta": "fg:#666666 bg:#1a1a1a",
            "completion-menu.meta.completion.current": "fg:#ffffff bg:#0066cc",
        }
    )
    prompt_session: PromptSession[str] = PromptSession(
        message=HTML(f"<b><style fg='{theme.ACCENT}'>You: </style></b>"),
        bottom_toolbar=toolbar_callback,
        style=prompt_style,
        completer=chat_completer,
        key_bindings=key_bindings,
        complete_style=CompleteStyle.COLUMN,  # Show single-column popup menu
        multiline=True,  # Enable multi-line input (Esc+Enter or Alt+Enter for newline)
    )

    # Divider before chat starts
    terminal_width = shutil.get_terminal_size().columns
    console.print("─" * terminal_width, style="dim")

    while True:
        try:
            # Get user input with prompt_toolkit async (supports status line)
            try:
                user_message = await prompt_session.prompt_async()
            except (KeyboardInterrupt, EOFError):
                console.print(
                    f"\n[{theme.WARNING}]{t('ai.chat_ended')}[/{theme.WARNING}]"
                )
                break

            # Handle slash commands first
            if command_handler.is_slash_command(user_message):
                result = await command_handler.execute(user_message)
                if result:
                    if result.message:
                        style = theme.ERROR if not result.success else "dim"
                        console.print(Panel(result.message, border_style=style))
                    if result.should_exit:
                        break
                    if result.new_conversation_id == "new":
                        current_conversation_id = None
                        command_handler.current_conversation_id = None
                    # Update session state if command changed settings
                    if result.update_provider or result.update_model:
                        session_state.update_provider(
                            result.update_provider or session_state.provider,
                            result.update_model or session_state.model,
                        )

                continue

            # Check for exit commands (kept for backwards compatibility)
            if user_message.lower().strip() in ["exit", "quit", "bye", "q"]:
                console.print(f"[{theme.WARNING}]{t('ai.goodbye')}[/{theme.WARNING}]")
                break

            if not user_message.strip():
                console.print(f"[dim]{t('ai.enter_message_hint')}[/dim]")
                continue

            console.print()  # Blank line between You: and Illiana:

            use_streaming = _use_streaming(ai_service.config.provider)

            try:
                if use_streaming:
                    returned_conversation_id = await _stream_chat_response(
                        ai_service,
                        user_message,
                        current_conversation_id,
                        "cli-user",
                        session_state=session_state,
                    )
                    if returned_conversation_id:
                        current_conversation_id = returned_conversation_id
                        command_handler.current_conversation_id = (
                            returned_conversation_id
                        )
                else:
                    # Show thinking spinner for non-streaming responses
                    from rich.live import Live
                    from rich.spinner import Spinner

                    spinner = Spinner("dots", text=t("ai.thinking"), style=theme.ACCENT)
                    spinner_live = Live(
                        spinner,
                        console=console,
                        refresh_per_second=20,
                        transient=True,
                    )
                    spinner_live.start()

                    try:
                        response = await ai_service.chat(
                            message=user_message,
                            conversation_id=current_conversation_id,
                            user_id="cli-user",
                        )
                    finally:
                        spinner_live.stop()

                    # Use shared rendering functions
                    from app.cli.ai_rendering import (
                        render_ai_header,
                        render_markdown_response,
                    )

                    render_ai_header(console, inline=True)
                    render_markdown_response(console, response.content)

                    # Update conversation reference
                    current_conversation_id = response.metadata.get(
                        "conversation_id", current_conversation_id
                    )
                    command_handler.current_conversation_id = current_conversation_id
            except ProviderNotInstalledError as e:
                # Clean display for missing provider
                console.print()
                missing_label = t("ai.provider_not_installed", provider=e.provider)
                console.print(f"[{theme.WARNING}]{missing_label}[/{theme.WARNING}]")
                console.print()
                install_label = t("ai.run_to_install", command=e.cli_command)
                console.print(f"[{theme.ACCENT}]{install_label}[/{theme.ACCENT}]")
                console.print()
            except Exception as stream_error:
                console.print(
                    f"[{theme.ERROR}]{t('shared.error')} {stream_error}[/{theme.ERROR}]"
                )
                console.print(
                    "[dim]Try a different provider or check your connection.[/dim]"
                )

            console.print()  # Add space after response

        except Exception as e:
            console.print(f"[{theme.ERROR}]{t('shared.error')} {e}[/{theme.ERROR}]")
            console.print(
                "[dim]You can continue chatting or type 'exit' to quit.[/dim]"
            )
