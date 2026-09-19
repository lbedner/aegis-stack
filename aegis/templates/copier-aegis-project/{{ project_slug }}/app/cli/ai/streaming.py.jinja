"""One turn of chat: send it, and stream the answer back."""

import typer

from app.cli import theme
from app.cli.ai.shared import _use_streaming
from app.cli.status_line import ChatSessionState
from app.i18n import t

from ...core.config import settings
from ...services.ai.domains.llm.providers import ProviderNotInstalledError

console = theme.console()


async def _send_message(
    ai_service,
    message: str,
    conversation_id: str | None,
    user_id: str,
    stream: bool,
    verbose: bool,
) -> None:
    """Send a single message and display the response."""
    use_streaming = _use_streaming(ai_service.config.provider, requested=stream)

    if use_streaming:
        await _stream_chat_response(
            ai_service,
            message,
            conversation_id,
            user_id,
            verbose=verbose,
        )
    else:
        # Show thinking spinner for non-streaming responses
        from rich.live import Live
        from rich.spinner import Spinner

        spinner = Spinner("dots", text=t("ai.thinking"), style=theme.ACCENT)
        spinner_live = Live(
            spinner, console=console, refresh_per_second=20, transient=True
        )
        spinner_live.start()

        try:
            response = await ai_service.chat(
                message=message,
                conversation_id=conversation_id,
                user_id=user_id,
            )
        finally:
            spinner_live.stop()

        # Use shared rendering functions
        from app.cli.ai_rendering import (
            render_ai_header,
            render_conversation_metadata,
            render_markdown_response,
        )

        # Show conversation info (only in verbose mode)
        conv_id = response.metadata.get("conversation_id", "unknown")
        conversation = await ai_service.get_conversation(conv_id)
        if verbose and conversation:
            typer.echo(t("ai.conversation_id_label", id=conversation.id))
            if conversation.title:
                typer.echo(t("ai.title_label", title=conversation.title))
            console.print()

        # Render response
        console.print()  # Blank line between You: and Illiana:
        render_ai_header(console, inline=True)
        render_markdown_response(console, response.content)

        # Show response metadata (only in verbose mode)
        if verbose and conversation:
            response_time = conversation.metadata.get("last_response_time_ms")
            render_conversation_metadata(
                console,
                conversation.id,
                message_count=conversation.get_message_count(),
                response_time=response_time,
            )


async def _stream_chat_response(
    ai_service,
    message: str,
    conversation_id: str | None,
    user_id: str,
    verbose: bool = False,
    session_state: ChatSessionState | None = None,
) -> str | None:
    """
    Stream chat response with real-time markdown rendering.

    Returns:
        The conversation ID for continuing the conversation, or None if interrupted.
    """
    import signal

    from rich.live import Live
    from rich.spinner import Spinner

    from app.cli.ai_rendering import StreamingMarkdownRenderer

    renderer = StreamingMarkdownRenderer(console)
    conversation_info = None
    response_time = None

    # Set up signal handler for graceful interruption
    interrupted = False

    def signal_handler(signum, frame):
        nonlocal interrupted
        interrupted = True

    old_handler = signal.signal(signal.SIGINT, signal_handler)

    try:
        header_shown = False
        import asyncio

        # Show thinking spinner initially
        spinner = Spinner("dots", text=t("ai.thinking"), style=theme.ACCENT)
        spinner_live = Live(
            spinner, console=console, refresh_per_second=20, transient=True
        )
        spinner_live.start()

        try:
            processed_content = set()

            async with asyncio.timeout(settings.AI_TIMEOUT_SECONDS):
                async for chunk in ai_service.stream_chat(
                    message=message,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    stream_delta=True,
                ):
                    if interrupted:
                        spinner_live.stop()
                        console.print("\nStreaming interrupted", style=theme.WARNING)
                        break

                    # Skip duplicate content only for non-delta mode (fake streaming)
                    # Delta mode sends unique incremental content that should never
                    # be skipped - LangChain sends character-level tokens where
                    # common chars like "a", "i", "e" would be incorrectly filtered
                    if not chunk.is_delta:
                        if chunk.content in processed_content:
                            if chunk.is_final:
                                conversation_info = chunk.conversation_id
                                response_time = chunk.metadata.get("response_time_ms")
                            continue
                        processed_content.add(chunk.content)

                    if chunk.is_delta and chunk.content:
                        if not header_shown:
                            spinner_live.stop()
                            console.print(
                                t("ai.header_inline"), style=theme.ACCENT, end=""
                            )
                            header_shown = True
                        renderer.add_delta(chunk.content)

                    if chunk.is_final:
                        conversation_info = chunk.conversation_id
                        response_time = chunk.metadata.get("response_time_ms")

                        # Update status line token count and cost
                        if session_state is not None:
                            input_tokens = chunk.metadata.get("input_tokens", 0)
                            output_tokens = chunk.metadata.get("output_tokens", 0)
                            cost = chunk.metadata.get("cost", 0.0)
                            session_state.add_tokens(input_tokens, output_tokens)
                            session_state.add_cost(cost)

                            # Persist cumulative totals to conversation metadata
                            if conversation_info:
                                conversation = await ai_service.get_conversation(
                                    conversation_info
                                )
                                if conversation:
                                    conversation.metadata["cumulative_tokens"] = (
                                        session_state.cumulative_tokens
                                    )
                                    conversation.metadata["cumulative_cost"] = (
                                        session_state.cumulative_cost
                                    )
                                    await ai_service.conversation_manager.save_conversation(
                                        conversation
                                    )

                        break
        except TimeoutError:
            spinner_live.stop()
            console.print(
                f"\n{t('shared.error')} {t('ai.timeout_error')}",
                style=theme.ERROR,
            )
            return None
        except RuntimeError as e:
            # WORKAROUND: anyio/prompt_toolkit event loop incompatibility
            # When PydanticAI's anyio-based streaming completes inside prompt_toolkit's
            # asyncio loop, the cancel scope cleanup can raise RuntimeError. The
            # response is already fully streamed at this point, so we ignore it.
            # String matching is intentional - no specific exception type exists.
            if "cancel scope" in str(e).lower():
                pass  # Response streamed successfully, ignore cleanup error
            else:
                raise
        finally:
            if spinner_live.is_started:
                spinner_live.stop()

        if not interrupted:
            renderer.finalize()
            console.print()

            if verbose and conversation_info:
                conversation = await ai_service.get_conversation(conversation_info)
                if conversation:
                    console.print(
                        f"{t('ai.conversation_label')} {conversation.id}", style="dim"
                    )
                    console.print(
                        f"{t('ai.messages_label')} {conversation.get_message_count()}",
                        style="dim",
                    )
                    if response_time:
                        console.print(
                            f"{t('ai.response_time_label')} {response_time:.1f}ms",
                            style="dim",
                        )

    except ProviderNotInstalledError as e:
        # Clean display for missing provider - no need to re-raise
        console.print()
        missing_label = t("ai.provider_not_installed", provider=e.provider)
        console.print(f"[{theme.WARNING}]{missing_label}[/{theme.WARNING}]")
        console.print()
        install_label = t("ai.run_to_install", command=e.cli_command)
        console.print(f"[{theme.ACCENT}]{install_label}[/{theme.ACCENT}]")
        console.print()
        return None

    except Exception as e:
        # WORKAROUND: Same anyio/prompt_toolkit issue can bubble up here
        # See inner handler comment for full explanation
        if "cancel scope" in str(e).lower():
            pass  # Response streamed successfully, ignore cleanup error
        elif not interrupted:
            console.print(f"Streaming error: {e}", style=theme.ERROR)
            raise

    finally:
        signal.signal(signal.SIGINT, old_handler)

    return conversation_info if not interrupted else None
