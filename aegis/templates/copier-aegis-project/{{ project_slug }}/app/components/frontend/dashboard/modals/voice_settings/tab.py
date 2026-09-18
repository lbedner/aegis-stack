"""The voice tab itself: the panels, in order."""

import asyncio
import contextlib
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.voice_settings.recorder import (
    STTRecorderSection,
)
from app.components.frontend.dashboard.modals.voice_settings.sections import (
    STTSettingsSection,
    TTSSettingsSection,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings


class VoiceSettingsTab(ft.Container):
    """
    Voice Settings tab content for the AI Service modal.

    Fetches and displays voice configuration for TTS and STT services.
    """

    def __init__(self) -> None:
        """Initialize Voice Settings tab."""
        super().__init__()

        # State
        self._settings: dict[str, Any] = {}
        self._tts_providers: list[dict[str, Any]] = []
        self._tts_models: list[dict[str, Any]] = []
        self._tts_voices: list[dict[str, Any]] = []
        self._stt_providers: list[dict[str, Any]] = []
        self._stt_models: list[dict[str, Any]] = []

        # Audio player for previews
        self._audio_player: ft.Audio | None = None
        self._current_preview_speed: float = 1.0

        # Reference to TTS section for preview control
        self._tts_section: TTSSettingsSection | None = None

        # Reference to STT recorder section
        self._stt_recorder: STTRecorderSection | None = None

        # Content container that will be updated after data loads
        self._content_column = ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.ProgressBar(),
                            SecondaryText("Loading voice settings..."),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.MD,
                    ),
                    padding=Theme.Spacing.XL,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )

        self.content = self._content_column

    def did_mount(self) -> None:
        """Called when the control is added to the page. Fetches data."""
        self.page.run_task(self._load_data)

    async def _load_data(self) -> None:
        """Fetch voice settings and catalog from API."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client

        # Fan out the bootstrap fetches.
        settings_data, tts_providers, stt_providers = await asyncio.gather(
            api.get("/api/v1/voice/settings"),
            api.get("/api/v1/voice/catalog/tts/providers"),
            api.get("/api/v1/voice/catalog/stt/providers"),
        )
        if not isinstance(settings_data, dict):
            self._render_error("Could not load voice settings.")
            return

        self._settings = settings_data
        self._tts_providers = tts_providers if isinstance(tts_providers, list) else []
        self._stt_providers = stt_providers if isinstance(stt_providers, list) else []

        # Current provider's catalog (models + voices for TTS, models for STT).
        tts_provider = self._settings.get("tts_provider", "openai")
        stt_provider = self._settings.get("stt_provider", "openai_whisper")
        tts_models, tts_voices, stt_models = await asyncio.gather(
            api.get(f"/api/v1/voice/catalog/tts/{tts_provider}/models"),
            api.get(f"/api/v1/voice/catalog/tts/{tts_provider}/voices"),
            api.get(f"/api/v1/voice/catalog/stt/{stt_provider}/models"),
        )
        if isinstance(tts_models, list):
            self._tts_models = tts_models
        if isinstance(tts_voices, list):
            self._tts_voices = tts_voices
        if isinstance(stt_models, list):
            self._stt_models = stt_models

        self._render_settings()

    def _render_settings(self) -> None:
        """Render the settings sections with loaded data."""
        # Refresh button row
        refresh_row = ft.Row(
            [
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Refresh settings",
                    on_click=self._on_refresh_click,
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
        )

        # TTS Section
        self._tts_section = TTSSettingsSection(
            current_settings=self._settings,
            providers=self._tts_providers,
            models=self._tts_models,
            voices=self._tts_voices,
            on_provider_change=self._on_tts_provider_change,
            on_model_change=self._on_tts_model_change,
            on_voice_change=self._on_voice_change,
            on_voice_preview=self._on_voice_preview,
            on_speed_change=self._on_speed_change,
        )

        # STT Section
        stt_section = STTSettingsSection(
            current_settings=self._settings,
            providers=self._stt_providers,
            models=self._stt_models,
            on_provider_change=self._on_stt_provider_change,
            on_model_change=self._on_stt_model_change,
        )

        # STT Recorder Section
        self._stt_recorder = STTRecorderSection(
            current_settings=self._settings,
        )

        self._content_column.controls = [
            refresh_row,
            self._tts_section,
            stt_section,
            self._stt_recorder,
        ]
        self._content_column.scroll = ft.ScrollMode.AUTO
        self._content_column.spacing = 0
        self.update()

    def _render_error(self, message: str) -> None:
        """Render an error state."""
        self._content_column.controls = [
            ft.Container(
                content=ft.Icon(
                    ft.Icons.ERROR_OUTLINE,
                    size=48,
                    color=Theme.Colors.ERROR,
                ),
                alignment=ft.alignment.center,
                padding=Theme.Spacing.MD,
            ),
            ft.Container(
                content=H3Text("Failed to load voice settings"),
                alignment=ft.alignment.center,
            ),
            ft.Container(
                content=SecondaryText(message),
                alignment=ft.alignment.center,
            ),
        ]
        self._content_column.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.update()

    async def _on_refresh_click(self, e: ft.ControlEvent) -> None:
        """Handle refresh button click."""
        self._content_column.controls = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.ProgressBar(),
                        SecondaryText("Refreshing..."),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.MD,
                ),
                padding=Theme.Spacing.XL,
            ),
        ]
        self._content_column.spacing = Theme.Spacing.MD
        self.update()

        await self._load_data()

    def _on_tts_provider_change(self, e: ft.ControlEvent) -> None:
        """Handle TTS provider change."""
        new_provider = e.control.value
        self._settings["tts_provider"] = new_provider
        # Reload models and voices for new provider
        self.page.run_task(self._reload_tts_catalog, new_provider)

    async def _reload_tts_catalog(self, provider_id: str) -> None:
        """Reload TTS models and voices for a provider."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        models, voices = await asyncio.gather(
            api.get(f"/api/v1/voice/catalog/tts/{provider_id}/models"),
            api.get(f"/api/v1/voice/catalog/tts/{provider_id}/voices"),
        )
        if isinstance(models, list):
            self._tts_models = models
        if isinstance(voices, list):
            self._tts_voices = voices
        self._render_settings()

    def _on_tts_model_change(self, e: ft.ControlEvent) -> None:
        """Handle TTS model change."""
        self._settings["tts_model"] = e.control.value

    def _on_voice_change(self, e: ft.ControlEvent) -> None:
        """Handle voice dropdown change."""
        voice_id = e.control.value
        self._settings["tts_voice"] = voice_id

        # Update preview player with new voice info
        if self._tts_section:
            voice_info = self._tts_section._get_voice_info(voice_id)
            self._tts_section.preview_player.set_voice(
                voice_info.get("name", ""),
                voice_info.get("description", ""),
            )

    def _on_voice_preview(self, text: str) -> None:
        """Handle voice preview request."""
        from app.core.log import logger

        voice_id = self._settings.get("tts_voice", "alloy")
        speed = self._settings.get("tts_speed", 1.0)
        logger.info(f"Voice preview requested for: {voice_id} at {speed}x speed")
        self.page.run_task(self._play_voice_preview, voice_id, text, speed)

    def _on_audio_state_changed(self, e: ft.ControlEvent) -> None:
        """Handle audio player state changes to clean up after playback."""
        from app.core.log import logger

        logger.info(f"Audio state changed: {e.data}")

        # Update visualizer state
        if e.data == "playing":
            if self._tts_section:
                self._tts_section.preview_player.set_playing(
                    True, self._current_preview_speed
                )
        elif e.data in ("completed", "paused", "stopped"):
            if self._tts_section:
                self._tts_section.preview_player.set_playing(False)

            # Clean up when playback completes
            if e.data == "completed" and self._audio_player is not None:
                with contextlib.suppress(Exception):
                    self.page.overlay.remove(self._audio_player)
                    logger.info("Audio player removed from overlay after playback")
                self._audio_player = None
                self.page.update()

    async def _play_voice_preview(self, voice_id: str, text: str, speed: float) -> None:
        """Generate and play voice preview."""
        import time
        from urllib.parse import quote

        from app.core.log import logger

        try:
            # If already playing, stop
            if self._audio_player is not None:
                logger.info("Stopping current preview")
                with contextlib.suppress(Exception):
                    self.page.overlay.remove(self._audio_player)
                self._audio_player = None
                if self._tts_section:
                    self._tts_section.preview_player.set_playing(False)
                self.page.update()
                return

            # Use a GET endpoint with query param for browser audio playback
            # Add cache buster to force reload each time
            cache_buster = int(time.time() * 1000)
            encoded_text = quote(text)
            audio_url = f"http://localhost:{settings.PORT}/api/v1/voice/preview/{voice_id}?text={encoded_text}&speed={speed}&t={cache_buster}"

            # Store speed for animation
            self._current_preview_speed = speed

            logger.info(f"Playing voice preview: {audio_url}")

            # Create new audio player with state change handler
            self._audio_player = ft.Audio(
                src=audio_url,
                autoplay=True,
                volume=1.0,
                on_state_changed=self._on_audio_state_changed,
            )
            self.page.overlay.append(self._audio_player)
            logger.info(
                f"Audio player added to overlay, overlay count: {len(self.page.overlay)}"
            )

            # Start visualizer animation immediately
            if self._tts_section:
                self._tts_section.preview_player.set_playing(True, speed)

            self.page.update()

        except Exception as e:
            logger.exception(f"Preview error: {e}")
            if self._tts_section:
                self._tts_section.preview_player.set_playing(False)
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(f"Preview error: {e}"),
                bgcolor=Theme.Colors.ERROR,
            )
            self.page.snack_bar.open = True
            self.page.update()

    def _on_speed_change(self, e: ft.ControlEvent) -> None:
        """Handle speed slider change."""
        self._settings["tts_speed"] = round(e.control.value, 2)

    def _on_stt_provider_change(self, e: ft.ControlEvent) -> None:
        """Handle STT provider change."""
        new_provider = e.control.value
        self._settings["stt_provider"] = new_provider
        self.page.run_task(self._reload_stt_catalog, new_provider)

    async def _reload_stt_catalog(self, provider_id: str) -> None:
        """Reload STT models for a provider."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        models = await api.get(f"/api/v1/voice/catalog/stt/{provider_id}/models")
        if isinstance(models, list):
            self._stt_models = models
        self._render_settings()

    def _on_stt_model_change(self, e: ft.ControlEvent) -> None:
        """Handle STT model change."""
        self._settings["stt_model"] = e.control.value
