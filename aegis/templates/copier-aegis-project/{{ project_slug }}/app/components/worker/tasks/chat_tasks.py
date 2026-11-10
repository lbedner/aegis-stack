"""Chat's work off the request path, as worker tasks (arq form).

Registered in the system queue, only where the paste index and the
documents service are. The body imports the AI service lazily, as
``document_tasks`` imports documents.
"""

from typing import Any


async def read_photo_task(
    ctx: dict[str, Any], user_id: str, key: str, media_type: str, title: str
) -> dict[str, Any]:
    """Keep a picture shared in chat and read what it showed: a vision
    call, so never on the request path. Later turns read it with
    ``pasted``."""
    from app.services.ai.service import read_photo_job

    return {"key": key, "read": await read_photo_job(user_id, key, media_type, title)}
