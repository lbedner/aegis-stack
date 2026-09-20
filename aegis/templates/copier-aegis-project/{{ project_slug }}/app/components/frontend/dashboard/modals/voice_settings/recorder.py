"""Recording, transcribing, and handing the result to the agent."""

from collections.abc import Awaitable, Callable
import contextlib
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ThemedSwitch,
)
from app.components.frontend.dashboard.modals.voice_settings.controls import (
    AudioWaveVisualizer,
    CollapsibleSection,
)
from app.components.frontend.dashboard.modals.voice_settings.recorder_agent import (
    AgentRoundTripMixin,
)
from app.components.frontend.dashboard.modals.voice_settings.recorder_capture import (
    RecordingCaptureMixin,
)
from app.components.frontend.dashboard.modals.voice_settings.recorder_state import (
    RecorderState,
    RecordingState,
)
from app.components.frontend.theme import AegisTheme as Theme


class STTRecorderSection(
    RecordingCaptureMixin,
    AgentRoundTripMixin,
    RecorderState,
):
    """Voice recorder with transcription and agent integration."""

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

    def _show_error(self, message: str) -> None:
        """Show an error snackbar."""
        if self.page:
            from app.components.frontend.controls.snack_bar import (
                ErrorSnackBar,
            )

            ErrorSnackBar(message).launch(self.page)

    def _on_rerecord_click(self, e: ft.ControlEvent) -> None:
        """Handle re-record button click."""
        self._reset_to_idle()

    def _on_cancel_click(self, e: ft.ControlEvent) -> None:
        """Handle cancel button click."""
        self._reset_to_idle()
