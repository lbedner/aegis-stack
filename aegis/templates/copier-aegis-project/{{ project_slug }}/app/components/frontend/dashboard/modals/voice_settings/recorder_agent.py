"""What happens to a recording: transcribe, ask, speak the answer."""

import asyncio
import contextlib
import uuid

import flet as ft

from app.components.frontend.dashboard.modals.voice_settings.recorder_state import (
    RecorderState,
    RecordingState,
)
from app.core.config import settings


class AgentRoundTripMixin(RecorderState):
    """The half that talks to the server."""

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

    async def _on_send_click(self, e: ft.ControlEvent) -> None:
        """Handle send button click."""
        # Get the (possibly edited) text
        self._transcribed_text = self._transcription_field.value or ""
        if self._transcribed_text.strip():
            await self._send_to_agent()
        else:
            self._show_error("Please enter some text to send")

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
