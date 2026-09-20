"""The one AIService the /ai routes share.

Its own module because every sub-router needs it and the router that
assembles them imports those sub-routers - so it cannot be the one
holding the singleton.
"""

from app.core.config import settings
from app.services.ai.service import AIService

ai_service = AIService(settings)
