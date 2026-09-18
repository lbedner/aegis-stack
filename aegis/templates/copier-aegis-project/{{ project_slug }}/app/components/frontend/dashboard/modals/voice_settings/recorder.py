"""Recording, transcribing, and handing the result to the agent."""

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    ThemedSwitch,
)
from app.components.frontend.dashboard.modals.voice_settings.controls import (
    AudioWaveVisualizer,
    CollapsibleSection,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings


class RecordingState(str, Enum):
    """States for the audio recording workflow."""

    IDLE = "idle"  # Ready to record
    RECORDING = "recording"  # ft.AudioRecorder active
    PROCESSING = "processing"  # Transcribing audio
    REVIEW = "review"  # Showing transcription for edit
    SENDING = "sending"  # Calling /ai/chat
    PLAYING = "playing"  # Playing TTS response


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
