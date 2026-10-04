"""Voice tables (``ai[voice]``): the voice profiles and the live-call
engines. A package of their own, so ``ai_voice`` owns their migration."""

from .live_engine import LiveEngine
from .profile import VoiceProfile

__all__ = ["LiveEngine", "VoiceProfile"]
