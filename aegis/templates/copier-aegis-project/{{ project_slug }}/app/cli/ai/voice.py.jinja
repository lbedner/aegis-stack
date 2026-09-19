"""The voice round trip: speak, transcribe, answer, speak back."""

import asyncio

import typer

from app.cli import theme
from app.cli.ai.shared import (
    app,
    console,
)
from app.i18n import lazy_t, t

from ...core.config import settings
from ...core.log import suppress_logs


@app.command(help=lazy_t("ai.help_voice"))
def voice(
    audio_file: str = typer.Argument(..., help=lazy_t("ai.arg_audio_file")),
    conversation_id: str | None = typer.Option(
        None, "--conversation-id", "-c", help=lazy_t("ai.opt_conversation_id")
    ),
    voice_mode: bool = typer.Option(
        False, "--voice", "-v", help=lazy_t("ai.opt_voice_mode")
    ),
    user_id: str = typer.Option(
        "cli-user", "--user-id", "-u", help=lazy_t("ai.opt_user_id")
    ),
) -> None:
    from pathlib import Path

    from app.services.ai.domains.voice import AudioFormat, AudioInput
    from app.services.ai.service import AIService

    async def run_voice() -> None:
        try:
            # Validate file exists
            audio_path = Path(audio_file)
            if not audio_path.exists():
                err_label = t("shared.error")
                detail = t("ai.file_not_found", path=audio_file)
                console.print(f"[{theme.ERROR}]{err_label}[/{theme.ERROR}] {detail}")
                raise typer.Exit(1)

            # Determine audio format
            ext = audio_path.suffix[1:].lower() if audio_path.suffix else "wav"
            try:
                audio_format = AudioFormat(ext)
            except ValueError:
                supported = ", ".join(f.value for f in AudioFormat)
                err_label = t("shared.error")
                detail = t("ai.unsupported_format", ext=ext)
                console.print(f"[{theme.ERROR}]{err_label}[/{theme.ERROR}] {detail}")
                console.print(
                    f"[dim]{t('ai.supported_formats', formats=supported)}[/dim]"
                )
                raise typer.Exit(1)

            # Read audio file
            with open(audio_path, "rb") as f:
                audio_content = f.read()

            audio_input = AudioInput(
                content=audio_content,
                format=audio_format,
            )

            with suppress_logs():
                ai_service = AIService(settings)

            # Show transcription progress
            from rich.progress import Progress, SpinnerColumn, TextColumn

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                progress.add_task(description=t("ai.transcribing_audio"), total=None)

                # Transcribe and chat
                result = await ai_service.voice_chat(
                    audio=audio_input,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    voice_mode=voice_mode,
                )

            # Display results
            console.print()
            console.print(f"[bold]{t('ai.transcription_label')}[/bold]")
            console.print(f"  {result.transcription.text}")

            if result.transcription.language:
                lang_label = t(
                    "ai.language_label",
                    lang=result.transcription.language,
                )
                console.print(f"  [dim]{lang_label}[/dim]")
            if result.transcription.duration_seconds:
                duration_str = f"{result.transcription.duration_seconds:.1f}"
                duration_label = t("ai.speech_duration", duration=duration_str)
                console.print(f"  [dim]{duration_label}[/dim]")

            console.print()
            console.print(f"[bold]{t('ai.response_label')}[/bold]")
            if voice_mode:
                console.print(f"  {result.voice_response}")
                if result.voice_response != result.full_response:
                    console.print()
                    console.print(f"[dim]{t('ai.voice_hint')}[/dim]")
            else:
                # Render as markdown for full response
                from app.cli.ai_rendering import render_markdown_response

                render_markdown_response(console, result.full_response)

            if result.conversation_id:
                console.print()
                conv_label = t(
                    "ai.conversation_id_label",
                    id=result.conversation_id[:8],
                )
                console.print(f"[dim]{conv_label}...[/dim]")

        except KeyboardInterrupt:
            typer.echo(f"\n{t('ai.cancelled')}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[{theme.ERROR}]{t('shared.error')}[/{theme.ERROR}] {e}")
            raise typer.Exit(1)

    asyncio.run(run_voice())
