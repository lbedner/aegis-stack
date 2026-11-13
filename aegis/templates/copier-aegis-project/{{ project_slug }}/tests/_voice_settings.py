"""Settings as the voice config reads them, for a test that builds a voice
service or config from them: every voice setting at its default
(``VoiceSettings``), ``given`` over that. A bare MagicMock makes up any
setting it lacks, and the config takes what it makes up as the value.
"""

from typing import Any
from unittest.mock import MagicMock

from app.core.voice_settings import VoiceSettings, setting_default


def voice_settings(**given: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        name: setting_default(name) for name in VoiceSettings.model_fields
    }
    # Its default is the stack's (inference[kokoro_fastapi] sets one).
    defaults["SPEECH_BASE_URL"] = None
    return MagicMock(**(defaults | given))
