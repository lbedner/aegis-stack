"""Holding the button down: start, tick, stop, hand off."""

import asyncio

import flet as ft

from app.components.frontend.dashboard.modals.voice_settings.recorder_state import (
    RecorderState,
    RecordingState,
)
from app.components.frontend.theme import AegisTheme as Theme


class RecordingCaptureMixin(RecorderState):
    """The microphone half of the recorder."""

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
