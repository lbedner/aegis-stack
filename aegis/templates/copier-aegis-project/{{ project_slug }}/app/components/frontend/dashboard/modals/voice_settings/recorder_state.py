"""The recorder's stages, and the state they share."""

from enum import Enum
from typing import TYPE_CHECKING, Any

import flet as ft


class RecordingState(str, Enum):
    """States for the audio recording workflow."""

    IDLE = "idle"  # Ready to record
    RECORDING = "recording"  # ft.AudioRecorder active
    PROCESSING = "processing"  # Transcribing audio
    REVIEW = "review"  # Showing transcription for edit
    SENDING = "sending"  # Calling /ai/chat
    PLAYING = "playing"  # Playing TTS response


class RecorderState(ft.Container):  # type: ignore[misc]
    """State every recorder mixin reads; assigned by ``__init__``.

    Recording, transcribing and answering are three stages over one set
    of controls. This names that set (and, under ``TYPE_CHECKING``, the
    methods that live on the other modules), so each file type checks on
    its own and the real definitions win at runtime.
    """

    TEMP_RECORDING_PATH = "/tmp/aegis_recording.wav"

    _agent_response: str
    _audio_recorder: ft.AudioRecorder
    _auto_send: bool
    _auto_send_switch: Any
    _cancel_button: Any
    _conversation_id: str | None
    _duration_text: Any
    _on_send_to_agent: Any
    _play_response_button: Any
    _record_button: Any
    _recording_data_url: str | None
    _recording_start_time: float | None
    _rerecord_button: Any
    _response_audio: Any
    _response_card: ft.Container
    _response_text: Any
    _send_button: Any
    _settings: dict[str, Any]
    _state: RecordingState
    _status_text: Any
    _transcribed_text: str
    _transcription_card: ft.Container
    _transcription_field: Any
    _tts_enabled: bool
    _tts_switch: Any
    _visualizer: Any

    if TYPE_CHECKING:  # the real definitions live on the mixins / section

        def _on_recorder_state_changed(self, *args: Any, **kwargs: Any) -> Any: ...
        def _on_response_audio_state_changed(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...
        def _play_tts_response(self, *args: Any, **kwargs: Any) -> Any: ...
        def _reset_to_idle(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _send_to_agent(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_error(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_response(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_review(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _start_recording(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _stop_recording(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _transcribe_audio(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _update_duration(self, *args: Any, **kwargs: Any) -> Any: ...
