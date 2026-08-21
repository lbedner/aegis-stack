"""
Voice Settings Tab Component

Displays voice configuration for TTS and STT services,
allowing users to browse voices and preview them with animated visualizer.
"""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from enum import Enum
import random
from typing import Any
import uuid

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
    ThemedSwitch,
)
from app.components.frontend.controls.expand_arrow import ExpandArrow
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings

# =============================================================================
# Recording State Enum
# =============================================================================


class RecordingState(str, Enum):
    """States for the audio recording workflow."""

    IDLE = "idle"  # Ready to record
    RECORDING = "recording"  # ft.AudioRecorder active
    PROCESSING = "processing"  # Transcribing audio
    REVIEW = "review"  # Showing transcription for edit
    SENDING = "sending"  # Calling /ai/chat
    PLAYING = "playing"  # Playing TTS response


# =============================================================================
# Collapsible Section Component
# =============================================================================


class CollapsibleSection(ft.Container):
    """A section with a clickable header that expands/collapses content."""

    def __init__(
        self,
        title: str,
        content: ft.Control,
        initially_expanded: bool = True,
    ) -> None:
        super().__init__()

        self._expanded = initially_expanded
        self._arrow = ExpandArrow(expanded=initially_expanded)
        self._content_container = ft.Container(
            content=content,
            visible=initially_expanded,
            padding=ft.padding.only(
                top=Theme.Spacing.MD,
                left=Theme.Spacing.MD,
                right=Theme.Spacing.MD,
                bottom=Theme.Spacing.MD,
            ),
        )

        # Header row with arrow and title
        header = ft.Container(
            content=ft.Row(
                [
                    self._arrow,
                    ft.Text(title, weight=ft.FontWeight.W_600, size=14),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM,
                vertical=Theme.Spacing.SM,
            ),
            on_hover=self._on_hover,
        )

        # Clickable header
        clickable_header = ft.GestureDetector(
            content=header,
            on_tap=self._toggle,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        self.content = ft.Column(
            [clickable_header, self._content_container],
            spacing=0,
        )

    def _toggle(self, _e: ft.ControlEvent) -> None:
        """Toggle expansion state."""
        self._expanded = not self._expanded
        self._arrow.set_expanded(self._expanded)
        self._content_container.visible = self._expanded
        self.update()

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state."""
        if e.data == "true":
            e.control.bgcolor = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        else:
            e.control.bgcolor = None
        if e.control.page:
            e.control.update()


# =============================================================================
# Audio Wave Visualizer Component
# =============================================================================


class AudioWaveVisualizer(ft.Container):
    """Animated sound wave bars that pulse during audio playback."""

    NUM_BARS = 11
    BASE_INTERVAL = 0.1  # 100ms base animation interval

    def __init__(self) -> None:
        super().__init__()

        self._bars: list[ft.Container] = []
        self._is_playing = False
        self._speed = 1.0

        # Build bars with varying initial heights (wave pattern)
        base_heights = [8, 14, 20, 26, 32, 36, 32, 26, 20, 14, 8]
        for i in range(self.NUM_BARS):
            bar = ft.Container(
                width=6,
                height=base_heights[i],
                bgcolor=Theme.Colors.PRIMARY,
                border_radius=3,
                animate=ft.Animation(100, ft.AnimationCurve.EASE_IN_OUT),
            )
            self._bars.append(bar)

        self.content = ft.Row(
            self._bars,
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def start_animation(self, speed: float = 1.0) -> None:
        """Start the wave animation at the given speed."""
        self._is_playing = True
        self._speed = max(0.25, min(4.0, speed))  # Clamp to valid range
        if self.page:
            self.page.run_task(self._animate_bars)

    def stop_animation(self) -> None:
        """Stop the wave animation and reset bars."""
        self._is_playing = False
        # Reset to default heights
        base_heights = [8, 14, 20, 26, 32, 36, 32, 26, 20, 14, 8]
        for i, bar in enumerate(self._bars):
            bar.height = base_heights[i]
        if self.page:
            self.update()

    async def _animate_bars(self) -> None:
        """Animate bar heights in a wave pattern."""
        # Faster speed = shorter interval (more frequent updates)
        interval = self.BASE_INTERVAL / self._speed
        while self._is_playing:
            for bar in self._bars:
                # Randomize height between 8 and 40
                bar.height = random.randint(8, 40)
            if self.page:
                self.update()
            await asyncio.sleep(interval)


# =============================================================================
# Voice Preview Player Component
# =============================================================================


class VoicePreviewPlayer(ft.Container):
    """Preview player with play button, wave visualizer, and voice info."""

    DEFAULT_PREVIEW_TEXT = "Hello! This is a preview of my voice."

    def __init__(
        self,
        on_play: Callable[[str], None],
        voice_name: str = "",
        voice_description: str = "",
    ) -> None:
        super().__init__()

        self._on_play = on_play
        self._is_playing = False
        self._visualizer = AudioWaveVisualizer()

        self._play_button = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILLED,
            icon_size=48,
            icon_color=Theme.Colors.PRIMARY,
            on_click=self._on_play_click,
            tooltip="Preview voice",
        )

        self._voice_label = ft.Text(
            voice_name,
            size=14,
            weight=ft.FontWeight.W_600,
            text_align=ft.TextAlign.CENTER,
        )

        self._voice_description = SecondaryText(
            voice_description,
            size=12,
            text_align=ft.TextAlign.CENTER,
        )

        # Text input for custom preview text
        self._text_field = ft.TextField(
            value=self.DEFAULT_PREVIEW_TEXT,
            label="Preview text",
            hint_text="Enter text to speak...",
            multiline=True,
            min_lines=2,
            max_lines=3,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
        )

        # Layout: centered column with text field, button, visualizer, voice info
        self.content = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "VOICE PREVIEW",
                        size=10,
                        weight=ft.FontWeight.W_500,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=Theme.Spacing.SM),
                    self._text_field,
                    ft.Container(height=Theme.Spacing.SM),
                    ft.Row(
                        [self._play_button, self._visualizer],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.MD,
                    ),
                    ft.Container(height=Theme.Spacing.SM),
                    self._voice_label,
                    self._voice_description,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=Theme.Spacing.MD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=Theme.Components.CARD_RADIUS,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

    def _on_play_click(self, e: ft.ControlEvent) -> None:
        """Handle play button click."""
        if self._on_play:
            text = self._text_field.value or self.DEFAULT_PREVIEW_TEXT
            self._on_play(text)

    def set_playing(self, playing: bool, speed: float = 1.0) -> None:
        """Update play state and animation."""
        self._is_playing = playing
        if playing:
            self._play_button.icon = ft.Icons.STOP_CIRCLE
            self._visualizer.start_animation(speed)
        else:
            self._play_button.icon = ft.Icons.PLAY_CIRCLE_FILLED
            self._visualizer.stop_animation()
        self.update()

    def set_voice(self, name: str, description: str) -> None:
        """Update displayed voice info."""
        self._voice_label.value = name
        self._voice_description.value = description
        self.update()


# =============================================================================
# TTS Settings Section
# =============================================================================


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


# =============================================================================
# STT Settings Section
# =============================================================================


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


# =============================================================================
# STT Recorder Section
# =============================================================================


class STTRecorderSection(ft.Container):
    """Voice recorder with transcription and agent integration."""

    TEMP_RECORDING_PATH = "/tmp/aegis_recording.wav"

    def __init__(
        self,
        current_settings: dict[str, Any],
        on_send_to_agent: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()

        self._settings = current_settings
        self._on_send_to_agent = on_send_to_agent

        # State
        self._state = RecordingState.IDLE
        self._transcribed_text = ""
        self._agent_response = ""
        self._conversation_id: str | None = None
        self._recording_start_time: float = 0.0

        # Settings (in-memory, session-only)
        self._auto_send = False
        self._tts_enabled = True

        # Recording data (data URL in web mode)
        self._recording_data_url: str | None = None

        # Audio recorder (initialized in did_mount)
        self._audio_recorder: ft.AudioRecorder | None = None

        # TTS audio player for response
        self._response_audio: ft.Audio | None = None

        # Build UI components
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the recorder UI components."""
        # Settings toggles
        self._auto_send_switch = ThemedSwitch(
            value=False,
            on_change=self._on_auto_send_change,
            scale=0.8,
        )

        self._tts_switch = ThemedSwitch(
            value=True,
            on_change=self._on_tts_change,
            scale=0.8,
        )

        settings_row = ft.Row(
            [
                ft.Row(
                    [
                        ft.Text("Auto-send", size=12),
                        self._auto_send_switch,
                    ],
                    spacing=4,
                ),
                ft.Container(width=Theme.Spacing.LG),
                ft.Row(
                    [
                        ft.Text("Voice responses", size=12),
                        self._tts_switch,
                    ],
                    spacing=4,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Status text
        self._status_text = ft.Text(
            "Ready",
            size=12,
            color=ft.Colors.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
        )

        # Duration counter
        self._duration_text = ft.Text(
            "00:00",
            size=24,
            weight=ft.FontWeight.W_300,
            font_family="monospace",
            text_align=ft.TextAlign.CENTER,
        )

        # Record button
        self._record_button = ft.IconButton(
            icon=ft.Icons.MIC,
            icon_size=48,
            icon_color=Theme.Colors.PRIMARY,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            on_click=self._on_record_click,
            tooltip="Click to start recording",
        )

        # Audio wave visualizer (reuse existing component)
        self._visualizer = AudioWaveVisualizer()

        # Recorder card content
        recorder_card = ft.Container(
            content=ft.Column(
                [
                    self._status_text,
                    ft.Container(height=Theme.Spacing.SM),
                    self._record_button,
                    ft.Container(height=Theme.Spacing.SM),
                    self._visualizer,
                    ft.Container(height=Theme.Spacing.SM),
                    self._duration_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            padding=Theme.Spacing.MD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=Theme.Components.CARD_RADIUS,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

        # Transcription field (visible in REVIEW state)
        self._transcription_field = ft.TextField(
            multiline=True,
            min_lines=2,
            max_lines=4,
            label="Transcription",
            hint_text="Your speech will appear here...",
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
        )

        # Action buttons for review state
        self._send_button = ft.FilledButton(
            text="Send",
            icon=ft.Icons.SEND,
            on_click=self._on_send_click,
        )

        self._rerecord_button = ft.OutlinedButton(
            text="Re-record",
            icon=ft.Icons.REFRESH,
            on_click=self._on_rerecord_click,
        )

        self._cancel_button = ft.TextButton(
            text="Cancel",
            on_click=self._on_cancel_click,
        )

        action_row = ft.Row(
            [
                self._send_button,
                self._rerecord_button,
                self._cancel_button,
            ],
            spacing=Theme.Spacing.SM,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # Transcription card (hidden until REVIEW state)
        self._transcription_card = ft.Container(
            content=ft.Column(
                [
                    self._transcription_field,
                    ft.Container(height=Theme.Spacing.SM),
                    action_row,
                ],
                spacing=0,
            ),
            visible=False,
            padding=Theme.Spacing.MD,
        )

        # Response text (visible after agent reply)
        self._response_text = ft.Text(
            "",
            size=13,
            selectable=True,
        )

        self._play_response_button = ft.IconButton(
            icon=ft.Icons.VOLUME_UP,
            icon_size=24,
            icon_color=Theme.Colors.PRIMARY,
            tooltip="Play response",
            on_click=self._on_play_response_click,
            visible=False,
        )

        # Response card (hidden until we have a response)
        self._response_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.SMART_TOY,
                                size=16,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Text(
                                "Agent Response",
                                size=12,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Container(expand=True),
                            self._play_response_button,
                        ],
                        spacing=Theme.Spacing.SM,
                    ),
                    ft.Container(height=Theme.Spacing.SM),
                    self._response_text,
                ],
                spacing=0,
            ),
            visible=False,
            padding=Theme.Spacing.MD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=Theme.Components.CARD_RADIUS,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

        # Main content column
        section_content = ft.Column(
            [
                settings_row,
                ft.Container(height=Theme.Spacing.MD),
                recorder_card,
                self._transcription_card,
                ft.Container(height=Theme.Spacing.SM),
                self._response_card,
            ],
            spacing=0,
        )

        self.content = CollapsibleSection(
            title="Voice Recording",
            content=section_content,
            initially_expanded=True,
        )

    def did_mount(self) -> None:
        """Initialize AudioRecorder when component mounts."""
        from app.core.log import logger

        logger.info("STTRecorderSection did_mount called")
        self._audio_recorder = ft.AudioRecorder(
            audio_encoder=ft.AudioEncoder.WAV,
            on_state_changed=self._on_recorder_state_changed,
        )
        self.page.overlay.append(self._audio_recorder)
        self.page.update()  # Required to initialize the AudioRecorder
        logger.info(
            f"AudioRecorder initialized and added to overlay: {self._audio_recorder}"
        )

    def will_unmount(self) -> None:
        """Clean up AudioRecorder when component unmounts."""
        if self._audio_recorder and self.page:
            with contextlib.suppress(Exception):
                self.page.overlay.remove(self._audio_recorder)
        if self._response_audio and self.page:
            with contextlib.suppress(Exception):
                self.page.overlay.remove(self._response_audio)

    def _on_auto_send_change(self, e: ft.ControlEvent) -> None:
        """Handle auto-send toggle change."""
        self._auto_send = e.control.value

    def _on_tts_change(self, e: ft.ControlEvent) -> None:
        """Handle TTS toggle change."""
        self._tts_enabled = e.control.value

    async def _on_record_click(self, e: ft.ControlEvent) -> None:
        """Handle record button click - toggle recording."""
        from app.core.log import logger

        logger.info(f"Record button clicked, current state: {self._state}")
        logger.info(f"Audio recorder initialized: {self._audio_recorder is not None}")

        if self._state == RecordingState.IDLE:
            await self._start_recording()
        elif self._state == RecordingState.RECORDING:
            await self._stop_recording()

    async def _start_recording(self) -> None:
        """Start audio recording."""
        import time

        from app.core.log import logger

        logger.info("_start_recording called")

        if not self._audio_recorder:
            logger.error("AudioRecorder not initialized")
            self._show_error("Microphone not available. Please refresh the page.")
            return

        logger.info(f"AudioRecorder page: {self._audio_recorder.page}")

        try:
            self._state = RecordingState.RECORDING
            self._recording_start_time = time.time()
            logger.info("State set to RECORDING")

            # Update UI - show waiting for permission initially
            self._record_button.icon = ft.Icons.STOP
            self._record_button.icon_color = Theme.Colors.ERROR
            self._record_button.tooltip = "Click to stop recording"
            self._status_text.value = "Waiting for microphone..."
            self._status_text.color = ft.Colors.ORANGE
            self._visualizer.start_animation()

            # Hide previous cards
            self._transcription_card.visible = False
            self._response_card.visible = False

            self.update()

            # Start duration counter BEFORE calling start_recording (which may block)
            self.page.run_task(self._update_duration)

            # Start the recorder in a thread to avoid blocking UI
            # The on_state_changed callback will notify us when recording actually starts
            # Capture reference to avoid None issues in thread
            assert self._audio_recorder is not None  # Checked at start of function
            audio_recorder = self._audio_recorder
            output_path = self.TEMP_RECORDING_PATH

            def start_recorder() -> None:
                try:
                    audio_recorder.start_recording(
                        output_path,
                        wait_timeout=60,  # Give user time to grant permission
                    )
                    logger.info("start_recording returned successfully")
                except TimeoutError:
                    logger.warning("Timeout waiting for recording to start")
                except Exception as ex:
                    logger.exception(f"Error in start_recording: {ex}")

            # Run in thread so UI stays responsive
            import threading

            thread = threading.Thread(target=start_recorder, daemon=True)
            thread.start()

            logger.info("Recording start initiated (running in background)")

        except Exception as ex:
            logger.exception(f"Failed to start recording: {ex}")
            self._show_error(f"Recording failed: {ex}")
            self._reset_to_idle()

    async def _stop_recording(self) -> None:
        """Stop recording and trigger transcription."""
        from app.core.log import logger

        if not self._audio_recorder:
            return

        try:
            self._state = RecordingState.PROCESSING
            self._status_text.value = "Processing..."
            self._status_text.color = ft.Colors.ON_SURFACE_VARIANT
            self._visualizer.stop_animation()
            self._record_button.icon = ft.Icons.MIC
            self._record_button.icon_color = Theme.Colors.PRIMARY
            self._record_button.tooltip = "Click to start recording"
            self._record_button.disabled = True
            self.update()

            # Stop the recorder - in web mode this returns a data URL
            # Run in thread to avoid blocking UI
            assert self._audio_recorder is not None
            audio_recorder = self._audio_recorder

            def stop_recorder() -> None:
                try:
                    # In web mode, stop_recording returns a data URL
                    result = audio_recorder.stop_recording(wait_timeout=30)
                    logger.info(
                        f"stop_recording returned: {type(result)}, length: {len(result) if result else 0}"
                    )
                    # Store the result for transcription
                    self._recording_data_url = result
                except TimeoutError:
                    logger.warning("Timeout waiting for stop_recording")
                    self._recording_data_url = None
                except Exception as ex:
                    logger.exception(f"Error in stop_recording: {ex}")
                    self._recording_data_url = None

            import threading

            thread = threading.Thread(target=stop_recorder, daemon=True)
            thread.start()

            logger.info("Recording stop initiated (running in background)")
            # The on_state_changed callback will trigger transcription when STOPPED

        except Exception as ex:
            logger.exception(f"Failed to stop recording: {ex}")
            self._reset_to_idle()

    def _on_recorder_state_changed(self, e: ft.AudioRecorderStateChangeEvent) -> None:
        """Handle AudioRecorder state changes."""
        from app.core.log import logger

        logger.info(f"Recorder state changed: {e.state}")

        if e.state == ft.AudioRecorderState.RECORDING:
            # Recording actually started (permission was granted)
            self._status_text.value = "Recording..."
            self._status_text.color = Theme.Colors.ERROR
            if self.page:
                self.update()
        elif e.state == ft.AudioRecorderState.STOPPED:
            # Recording file is ready, transcribe it
            self.page.run_task(self._transcribe_audio)

    async def _update_duration(self) -> None:
        """Update the duration display while recording."""
        import time

        while self._state == RecordingState.RECORDING:
            elapsed = time.time() - self._recording_start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self._duration_text.value = f"{minutes:02d}:{seconds:02d}"
            if self.page:
                self._duration_text.update()
            await asyncio.sleep(0.1)

    async def _transcribe_audio(self) -> None:
        """Send audio to transcription API."""
        import base64
        from pathlib import Path

        from app.core.log import logger

        try:
            # Wait a moment for the stop_recording thread to complete
            await asyncio.sleep(0.5)

            if not self._recording_data_url:
                logger.error("No recording data available")
                self._show_error("Recording failed - no audio data")
                self._reset_to_idle()
                return

            recording_result = self._recording_data_url
            logger.info(
                f"Processing recording result (length: {len(recording_result)})"
            )
            logger.info(f"Recording result preview: {recording_result[:100]}...")

            audio_bytes: bytes | None = None
            audio_format = "wav"
            filename = "recording.wav"
            mime_type = "audio/wav"

            # Handle different return formats from stop_recording():
            # 1. Blob URL (web mode): blob:http://localhost:8000/...
            # 2. File path (desktop mode): /tmp/aegis_recording.wav
            # 3. Data URL: data:audio/...;base64,...

            if recording_result.startswith("blob:"):
                # Web mode returns a blob URL - this is a browser-side reference
                # that cannot be accessed from Python server
                logger.warning(
                    "Web mode detected - blob URL cannot be accessed from server"
                )
                self._show_error(
                    "Voice recording is not yet supported in web browsers. "
                    "Please use the desktop app for voice recording."
                )
                self._reset_to_idle()
                return

            elif recording_result.startswith("data:"):
                # Data URL format: data:audio/webm;base64,<data>
                try:
                    header, b64_data = recording_result.split(",", 1)
                    audio_bytes = base64.b64decode(b64_data)
                    logger.info(f"Decoded {len(audio_bytes)} bytes from data URL")

                    # Determine audio format from header
                    if "audio/wav" in header:
                        audio_format = "wav"
                    elif "audio/webm" in header:
                        audio_format = "webm"
                    elif "audio/ogg" in header:
                        audio_format = "ogg"

                    filename = f"recording.{audio_format}"
                    mime_type = f"audio/{audio_format}"

                except Exception as ex:
                    logger.exception(f"Failed to decode data URL: {ex}")
                    self._show_error("Failed to decode recording")
                    self._reset_to_idle()
                    return

            else:
                # Assume it's a file path (desktop mode)
                file_path = Path(recording_result)
                if not file_path.exists():
                    logger.error(f"Recording file not found: {file_path}")
                    self._show_error("Recording file not found")
                    self._reset_to_idle()
                    return

                try:
                    audio_bytes = file_path.read_bytes()
                    logger.info(f"Read {len(audio_bytes)} bytes from file: {file_path}")

                    # Determine format from file extension
                    suffix = file_path.suffix.lower()
                    if suffix == ".wav":
                        audio_format = "wav"
                    elif suffix == ".webm":
                        audio_format = "webm"
                    elif suffix == ".ogg":
                        audio_format = "ogg"
                    elif suffix == ".mp3":
                        audio_format = "mp3"

                    filename = f"recording.{audio_format}"
                    mime_type = f"audio/{audio_format}"

                except Exception as ex:
                    logger.exception(f"Failed to read recording file: {ex}")
                    self._show_error("Failed to read recording file")
                    self._reset_to_idle()
                    return

            if not audio_bytes:
                logger.error("No audio bytes available")
                self._show_error("No audio data captured")
                self._reset_to_idle()
                return

            # Send to transcription API via APIClient. Bearer token + 401
            # → on_unauthorized are handled centrally; multipart boundary
            # is generated by httpx from ``files=``.
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            result = await api.post_multipart(
                "/api/v1/ai/transcribe",
                files={"file": (filename, audio_bytes, mime_type)},
            )
            if not isinstance(result, dict):
                logger.error("Transcription failed (no body returned)")
                self._show_error("Transcription failed")
                self._reset_to_idle()
                return

            self._transcribed_text = result.get("text", "")
            logger.info(
                f"Transcription result: {self._transcribed_text[:100] if self._transcribed_text else 'empty'}..."
            )

            # Clear the recording data
            self._recording_data_url = None

            # Either auto-send or show review
            if self._auto_send and self._transcribed_text:
                await self._send_to_agent()
            else:
                self._show_review()

        except Exception as ex:
            logger.exception(f"Transcription error: {ex}")
            self._show_error(f"Transcription error: {ex}")
            self._reset_to_idle()

    def _show_review(self) -> None:
        """Show the transcription for review/edit."""
        self._state = RecordingState.REVIEW
        self._transcription_field.value = self._transcribed_text
        self._transcription_card.visible = True
        self._status_text.value = "Review transcription"
        self._record_button.disabled = False
        self.update()

    def _reset_to_idle(self) -> None:
        """Reset to idle state."""
        self._state = RecordingState.IDLE
        self._record_button.icon = ft.Icons.MIC
        self._record_button.icon_color = Theme.Colors.PRIMARY
        self._record_button.tooltip = "Click to start recording"
        self._record_button.disabled = False
        self._status_text.value = "Ready"
        self._status_text.color = ft.Colors.ON_SURFACE_VARIANT
        self._duration_text.value = "00:00"
        self._visualizer.stop_animation()
        self._transcription_card.visible = False
        self.update()

    def _show_error(self, message: str) -> None:
        """Show an error snackbar."""
        if self.page:
            from app.components.frontend.controls.snack_bar import (
                ErrorSnackBar,
            )

            ErrorSnackBar(message).launch(self.page)

    async def _on_send_click(self, e: ft.ControlEvent) -> None:
        """Handle send button click."""
        # Get the (possibly edited) text
        self._transcribed_text = self._transcription_field.value or ""
        if self._transcribed_text.strip():
            await self._send_to_agent()
        else:
            self._show_error("Please enter some text to send")

    def _on_rerecord_click(self, e: ft.ControlEvent) -> None:
        """Handle re-record button click."""
        self._reset_to_idle()

    def _on_cancel_click(self, e: ft.ControlEvent) -> None:
        """Handle cancel button click."""
        self._reset_to_idle()

    async def _send_to_agent(self) -> None:
        """Send transcribed text to AI agent."""
        from app.core.log import logger

        try:
            self._state = RecordingState.SENDING
            self._status_text.value = "Sending to agent..."
            self._transcription_card.visible = False
            self._send_button.disabled = True
            self.update()

            # Generate conversation ID if we don't have one
            if not self._conversation_id:
                self._conversation_id = str(uuid.uuid4())

            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            result = await api.post(
                "/api/v1/ai/chat",
                json={
                    "message": self._transcribed_text,
                    "conversation_id": self._conversation_id,
                },
            )
            if not isinstance(result, dict):
                self._show_error("Chat failed.")
                self._reset_to_idle()
                return

            self._agent_response = result.get("message", result.get("response", ""))
            logger.info(f"Agent response: {self._agent_response[:100]}...")

            # Show response
            self._show_response()

            # Play TTS if enabled
            if self._tts_enabled and self._agent_response:
                await self._play_tts_response()

        except Exception as ex:
            logger.exception(f"Chat error: {ex}")
            self._show_error(f"Chat error: {ex}")
            self._reset_to_idle()

    def _show_response(self) -> None:
        """Show the agent response."""
        self._state = RecordingState.IDLE
        self._response_text.value = self._agent_response
        self._response_card.visible = True
        self._play_response_button.visible = self._tts_enabled
        self._status_text.value = "Ready"
        self._send_button.disabled = False
        self._record_button.disabled = False
        self.update()

    async def _play_tts_response(self) -> None:
        """Play the agent response using TTS."""
        import time
        from urllib.parse import quote

        from app.core.log import logger

        try:
            self._state = RecordingState.PLAYING

            # Get TTS settings
            voice_id = self._settings.get("tts_voice", "alloy")
            speed = self._settings.get("tts_speed", 1.0)

            # Build audio URL
            cache_buster = int(time.time() * 1000)
            encoded_text = quote(self._agent_response)
            audio_url = f"http://localhost:{settings.PORT}/api/v1/voice/preview/{voice_id}?text={encoded_text}&speed={speed}&t={cache_buster}"

            logger.info(f"Playing TTS response: {audio_url}")

            # Clean up previous audio if any
            if self._response_audio and self.page:
                with contextlib.suppress(Exception):
                    self.page.overlay.remove(self._response_audio)

            # Create and play audio
            self._response_audio = ft.Audio(
                src=audio_url,
                autoplay=True,
                volume=1.0,
                on_state_changed=self._on_response_audio_state_changed,
            )
            self.page.overlay.append(self._response_audio)
            self.page.update()

        except Exception as ex:
            logger.exception(f"TTS playback error: {ex}")
            self._state = RecordingState.IDLE

    def _on_response_audio_state_changed(self, e: ft.ControlEvent) -> None:
        """Handle response audio state changes."""
        from app.core.log import logger

        logger.info(f"Response audio state: {e.data}")

        if e.data == "completed":
            self._state = RecordingState.IDLE
            if self._response_audio and self.page:
                with contextlib.suppress(Exception):
                    self.page.overlay.remove(self._response_audio)
                self._response_audio = None

    async def _on_play_response_click(self, e: ft.ControlEvent) -> None:
        """Handle manual play response button click."""
        if self._agent_response:
            await self._play_tts_response()


# =============================================================================
# Main Voice Settings Tab
# =============================================================================


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
