"""The two settings panels: what speaks, and what listens."""

from collections.abc import Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.dashboard.modals.voice_settings.controls import (
    CollapsibleSection,
    VoicePreviewPlayer,
)
from app.components.frontend.theme import AegisTheme as Theme


class TTSSettingsSection(ft.Container):
    """TTS configuration section with provider, model, voice dropdown, and preview."""

    def __init__(
        self,
        current_settings: dict[str, Any],
        providers: list[dict[str, Any]],
        models: list[dict[str, Any]],
        voices: list[dict[str, Any]],
        on_provider_change: Callable[[ft.ControlEvent], None],
        on_model_change: Callable[[ft.ControlEvent], None],
        on_voice_change: Callable[[ft.ControlEvent], None],
        on_voice_preview: Callable[[str], None],
        on_speed_change: Callable[[ft.ControlEvent], None],
    ) -> None:
        super().__init__()

        self.voices = voices
        self.current_provider = current_settings.get("tts_provider", "openai")
        self.current_model = current_settings.get("tts_model", "tts-1")
        self.current_voice = current_settings.get("tts_voice", "alloy")
        self.current_speed = current_settings.get("tts_speed", 1.0)

        # Find current voice info
        current_voice_info = self._get_voice_info(self.current_voice)

        # Provider dropdown
        provider_dropdown = ft.Dropdown(
            label="Provider",
            value=self.current_provider,
            options=[
                ft.dropdown.Option(key=p["id"], text=p["name"]) for p in providers
            ],
            width=180,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            on_change=on_provider_change,
        )

        # Model dropdown
        model_dropdown = ft.Dropdown(
            label="Model",
            value=self.current_model,
            options=[
                ft.dropdown.Option(
                    key=m["id"],
                    text=f"{m['name']} ({m['quality']})",
                )
                for m in models
            ],
            width=180,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            on_change=on_model_change,
        )

        # Voice dropdown - shows "Name - Description"
        voice_options = []
        for v in voices:
            name = v.get("name", "Unknown")
            desc = v.get("description", "")
            # Truncate long descriptions
            if len(desc) > 30:
                desc = desc[:27] + "..."
            display_text = f"{name} - {desc}" if desc else name
            voice_options.append(
                ft.dropdown.Option(key=v.get("id", ""), text=display_text)
            )

        voice_dropdown = ft.Dropdown(
            label="Voice",
            value=self.current_voice,
            options=voice_options,
            width=280,
            max_menu_height=400,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            on_change=on_voice_change,
        )

        # Speed slider
        self._speed_label = SecondaryText(f"{self.current_speed}x", width=50)
        speed_slider = ft.Slider(
            min=0.25,
            max=4.0,
            value=self.current_speed,
            divisions=15,
            on_change=lambda e: self._on_speed_slider_change(e, on_speed_change),
        )

        speed_row = ft.Row(
            [
                SecondaryText("Speed:", width=50),
                ft.Container(speed_slider, expand=True),
                self._speed_label,
            ],
            spacing=Theme.Spacing.SM,
        )

        # Voice preview player
        self._preview_player = VoicePreviewPlayer(
            on_play=on_voice_preview,
            voice_name=current_voice_info.get("name", ""),
            voice_description=current_voice_info.get("description", ""),
        )

        section_content = ft.Column(
            [
                ft.Row(
                    [provider_dropdown, model_dropdown, voice_dropdown],
                    spacing=Theme.Spacing.MD,
                    wrap=True,
                ),
                ft.Container(height=Theme.Spacing.SM),
                speed_row,
                ft.Container(height=Theme.Spacing.MD),
                self._preview_player,
            ],
            spacing=0,
        )

        self.content = CollapsibleSection(
            title="Text-to-Speech (TTS)",
            content=section_content,
            initially_expanded=True,
        )

    def _get_voice_info(self, voice_id: str) -> dict[str, Any]:
        """Get voice info dict by ID."""
        for v in self.voices:
            if v.get("id") == voice_id:
                return v
        return {}

    def _on_speed_slider_change(
        self, e: ft.ControlEvent, callback: Callable[[ft.ControlEvent], None]
    ) -> None:
        """Handle speed slider change and update label."""
        self._speed_label.value = f"{round(e.control.value, 2)}x"
        self._speed_label.update()
        callback(e)

    @property
    def preview_player(self) -> VoicePreviewPlayer:
        """Access the preview player for external control."""
        return self._preview_player


class STTSettingsSection(ft.Container):
    """STT configuration section with provider and model selection."""

    def __init__(
        self,
        current_settings: dict[str, Any],
        providers: list[dict[str, Any]],
        models: list[dict[str, Any]],
        on_provider_change: Callable[[ft.ControlEvent], None],
        on_model_change: Callable[[ft.ControlEvent], None],
    ) -> None:
        super().__init__()

        self.current_provider = current_settings.get("stt_provider", "openai_whisper")
        self.current_model = current_settings.get("stt_model", "whisper-1")
        self.current_language = current_settings.get("stt_language")

        # Provider dropdown
        provider_dropdown = ft.Dropdown(
            label="Provider",
            value=self.current_provider,
            options=[
                ft.dropdown.Option(key=p["id"], text=p["name"]) for p in providers
            ],
            width=200,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            on_change=on_provider_change,
        )

        # Model dropdown
        model_dropdown = ft.Dropdown(
            label="Model",
            value=self.current_model,
            options=[
                ft.dropdown.Option(
                    key=m["id"],
                    text=f"{m['name']} ({m['quality']})",
                )
                for m in models
            ],
            width=250,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            on_change=on_model_change,
        )

        # Language field (optional)
        language_field = ft.TextField(
            label="Language (optional)",
            value=self.current_language or "",
            hint_text="e.g., en, es, fr (auto-detect if empty)",
            width=200,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
        )

        section_content = ft.Row(
            [provider_dropdown, model_dropdown, language_field],
            spacing=Theme.Spacing.MD,
        )

        self.content = CollapsibleSection(
            title="Speech-to-Text (STT)",
            content=section_content,
            initially_expanded=True,
        )
