"""Speech either way: transcribe a file, speak a line."""

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


@app.command(help=lazy_t("ai.help_transcribe"))
def transcribe(
    audio_file: str = typer.Argument(..., help=lazy_t("ai.arg_audio_file")),
    language: str | None = typer.Option(
        None, "--language", "-l", help=lazy_t("ai.opt_language")
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help=lazy_t("ai.opt_json")),
) -> None:
    import json
    from pathlib import Path

    from app.services.ai.domains.voice import AudioFormat, AudioInput
    from app.services.ai.service import AIService

    async def run_transcribe() -> None:
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
                language=language,
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
                progress.add_task(description=t("ai.transcribing"), total=None)
                result = await ai_service.stt.transcribe(audio_input)

            if json_output:
                # Output as JSON
                output = {
                    "text": result.text,
                    "language": result.language,
                    "duration_seconds": result.duration_seconds,
                    "confidence": result.confidence,
                    "provider": result.provider.value,
                }
                if result.segments:
                    output["segments"] = [
                        {
                            "text": seg.text,
                            "start": seg.start,
                            "end": seg.end,
                            "confidence": seg.confidence,
                        }
                        for seg in result.segments
                    ]
                print(json.dumps(output, indent=2))
            else:
                # Pretty output
                console.print()
                console.print(result.text)
                console.print()

                # Metadata
                meta_parts = []
                if result.language:
                    meta_parts.append(t("ai.language_label", lang=result.language))
                if result.duration_seconds:
                    meta_parts.append(
                        t(
                            "ai.speech_duration",
                            duration=f"{result.duration_seconds:.1f}",
                        )
                    )
                if result.confidence:
                    meta_parts.append(f"Confidence: {result.confidence:.1%}")
                meta_parts.append(t("ai.provider_info", provider=result.provider.value))

                console.print(f"[dim]{' | '.join(meta_parts)}[/dim]")

        except KeyboardInterrupt:
            typer.echo(f"\n{t('ai.cancelled')}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[{theme.ERROR}]{t('shared.error')}[/{theme.ERROR}] {e}")
            raise typer.Exit(1)

    asyncio.run(run_transcribe())


@app.command("stt-status", help=lazy_t("ai.help_stt_status"))
def stt_status() -> None:
    from app.services.ai.service import AIService

    with suppress_logs():
        ai_service = AIService(settings)

    status = ai_service.stt.get_status()

    theme.title(t("ai.stt_status_title"))
    theme.label("=" * 40)

    typer.echo(
        theme.label_text(t("ai.provider_label") + " ")
        + status.get("provider", "unknown")
    )
    typer.echo(
        theme.label_text(t("ai.model_label") + " ")
        + str(status.get("model", "default"))
    )

    initialized = status.get("initialized", False)
    status_text = (
        t("ai.svc_initialized") if initialized else t("ai.svc_not_initialized")
    )
    status_value = (
        theme.good_text(status_text) if initialized else theme.warn_text(status_text)
    )
    typer.echo(theme.label_text(t("ai.status_label") + " ") + status_value)


@app.command(help=lazy_t("ai.help_speak"))
def speak(
    text: str = typer.Argument(..., help=lazy_t("ai.arg_text")),
    output: str = typer.Option(
        "speech.mp3", "--output", "-o", help=lazy_t("ai.opt_output_file")
    ),
    voice: str | None = typer.Option(
        None, "--voice", "-v", help=lazy_t("ai.opt_voice")
    ),
    speed: float = typer.Option(
        1.0, "--speed", "-s", min=0.25, max=4.0, help=lazy_t("ai.opt_speed")
    ),
) -> None:
    from pathlib import Path

    from app.services.ai.domains.voice import SpeechRequest
    from app.services.ai.service import AIService

    async def run_speak() -> None:
        try:
            with suppress_logs():
                ai_service = AIService(settings)

            # Show synthesis progress
            from rich.progress import Progress, SpinnerColumn, TextColumn

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                progress.add_task(description=t("ai.synthesizing"), total=None)

                request = SpeechRequest(text=text, voice=voice, speed=speed)
                result = await ai_service.tts.synthesize(request)

            # Save audio to file
            output_path = Path(output)
            with open(output_path, "wb") as f:
                f.write(result.audio)

            console.print()
            console.print(
                f"[{theme.ACCENT}]✓[/{theme.ACCENT}] {t('ai.speech_saved', path=str(output_path))}"
            )
            console.print(
                f"  [dim]{t('ai.speech_format', format=result.format.value)}[/dim]"
            )
            console.print(
                f"  [dim]{t('ai.speech_size', size=f'{len(result.audio):,}')}[/dim]"
            )

            if result.duration_seconds:
                duration_str = f"{result.duration_seconds:.1f}"
                duration_label = t("ai.speech_duration", duration=duration_str)
                console.print(f"  [dim]{duration_label}[/dim]")

        except KeyboardInterrupt:
            typer.echo(f"\n{t('ai.cancelled')}", err=True)
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[{theme.ERROR}]{t('shared.error')}[/{theme.ERROR}] {e}")
            raise typer.Exit(1)

    asyncio.run(run_speak())


@app.command("tts-status", help=lazy_t("ai.help_tts_status"))
def tts_status() -> None:
    from app.services.ai.service import AIService

    with suppress_logs():
        ai_service = AIService(settings)

    status = ai_service.tts.get_status()

    theme.title(t("ai.tts_status_title"))
    theme.label("=" * 40)

    typer.echo(
        theme.label_text(t("ai.provider_label") + " ")
        + status.get("provider", "unknown")
    )
    typer.echo(
        theme.label_text(t("ai.model_label") + " ")
        + str(status.get("model", "default"))
    )
    typer.echo(
        theme.label_text(t("ai.voice_label") + " ")
        + str(status.get("voice", "default"))
    )
    typer.echo(
        theme.label_text(t("ai.speed_label") + " ") + str(status.get("speed", 1.0))
    )

    initialized = status.get("initialized", False)
    status_text = (
        t("ai.svc_initialized") if initialized else t("ai.svc_not_initialized")
    )
    status_value = (
        theme.good_text(status_text) if initialized else theme.warn_text(status_text)
    )
    typer.echo(theme.label_text(t("ai.status_label") + " ") + status_value)

    # Show available voices
    typer.echo()
    typer.echo(
        theme.label_text(t("ai.openai_voices") + " ")
        + "alloy, echo, fable, onyx, nova, shimmer"
    )
