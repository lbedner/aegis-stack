"""The voice settings tab, split by what each part does.

Was a single 1,649-line module. ``ai_modal`` imports VoiceSettingsTab
from here and did not have to change.
"""

from app.components.frontend.dashboard.modals.voice_settings.tab import (
    VoiceSettingsTab,
)

__all__ = ["VoiceSettingsTab"]
