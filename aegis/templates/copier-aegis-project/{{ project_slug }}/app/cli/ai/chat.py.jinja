"""Talking to the model, and what was said before."""

import asyncio

import typer

from app.cli.ai.session import _interactive_chat_session
from app.cli.ai.shared import (
    app,
    get_provider_display_name,
)
from app.cli.ai.streaming import _send_message
from app.i18n import lazy_t, t

from ...core.config import settings
from ...core.log import suppress_logs
from ...services.ai.models import (
    MessageRole,
)


@app.command(help=lazy_t("ai.help_chat"))
def chat(
    message: str | None = typer.Argument(None, help=lazy_t("ai.arg_message")),
    stream: bool = typer.Option(
        True, "--stream/--no-stream", help=lazy_t("ai.opt_stream")
    ),
    conversation_id: str | None = typer.Option(
        None, "--conversation-id", "-c", help=lazy_t("ai.opt_conversation_id")
    ),
    new: bool = typer.Option(False, "--new", "-n", help=lazy_t("ai.opt_new")),
    user_id: str = typer.Option(
        "cli-user", "--user-id", "-u", help=lazy_t("ai.opt_user_id")
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help=lazy_t("ai.opt_verbose")
    ),
) -> None:
    from app.services.ai.service import AIService

    async def run_chat() -> None:
        nonlocal conversation_id
        try:
            with suppress_logs():
                ai_service = AIService(settings)

                # Resume most recent conversation by default
                if not new and not conversation_id:
                    convos = await ai_service.list_conversations(user_id)
                    if convos:
                        conversation_id = convos[0].id
                        typer.echo(
                            t("ai.resuming_conversation", id=conversation_id[:8]),
                            err=True,
                        )

                if message:
                    # Single message mode
                    await _send_message(
                        ai_service,
                        message,
                        conversation_id,
                        user_id,
                        stream,
                        verbose,
                    )
                else:
                    # Interactive session mode
                    await _interactive_chat_session(
                        ai_service,
                        conversation_id,
                    )
        except KeyboardInterrupt:
            typer.echo("\nChat interrupted", err=True)
            raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"{t('shared.error')} {e}", err=True)
            raise typer.Exit(1)

    asyncio.run(run_chat())


@app.command(help=lazy_t("ai.help_conversations"))
def conversations(
    user_id: str = typer.Option(
        "cli-user", "--user-id", "-u", help=lazy_t("ai.opt_user_id")
    ),
    limit: int = typer.Option(10, "--limit", "-l", help=lazy_t("ai.opt_limit")),
) -> None:
    from app.services.ai.service import AIService

    with suppress_logs():
        ai_service = AIService(settings)
    convos = asyncio.run(ai_service.list_conversations(user_id))[:limit]

    if not convos:
        typer.echo(t("ai.no_conversations", user_id=user_id))
        return

    typer.echo(t("ai.conversations_for", user_id=user_id))
    typer.echo("")

    for conv in convos:
        title = conv.title or "Untitled"
        messages = conv.get_message_count()
        updated = conv.updated_at.strftime("%Y-%m-%d %H:%M")

        typer.echo(f"• {conv.id[:8]}... - {title}")
        typer.echo(f"  {t('ai.messages_count', count=messages)} | {updated}")
        typer.echo("")


@app.command(help=lazy_t("ai.help_history"))
def history(
    conversation_id: str = typer.Argument(..., help=lazy_t("ai.arg_conversation_id")),
    user_id: str = typer.Option(
        "cli-user", "--user-id", "-u", help=lazy_t("ai.opt_user_id")
    ),
) -> None:
    from app.services.ai.service import AIService

    with suppress_logs():
        ai_service = AIService(settings)
    conversation = asyncio.run(ai_service.get_conversation(conversation_id))

    if not conversation:
        typer.echo(
            f"{t('shared.error')} {t('ai.conversation_not_found', id=conversation_id)}"
        )
        raise typer.Exit(1)

    # Check if user owns conversation
    if conversation.metadata.get("user_id") != user_id:
        typer.echo(f"{t('shared.error')} {t('ai.access_denied')}")
        raise typer.Exit(1)

    typer.echo(t("ai.conversation_id_label", id=conversation_id))
    if conversation.title:
        typer.echo(t("ai.title_label", title=conversation.title))
    typer.echo(
        t("ai.provider_info", provider=get_provider_display_name(conversation.provider))
    )
    typer.echo(t("ai.messages_info", count=conversation.get_message_count()))
    typer.echo("")

    for i, msg in enumerate(conversation.messages):
        timestamp = msg.timestamp.strftime("%H:%M:%S")
        role_icon = "" if msg.role == MessageRole.USER else ""

        typer.echo(f"{role_icon} [{timestamp}] {msg.content}")
        if i < len(conversation.messages) - 1:
            typer.echo("")
