"""What the model cost, how it felt, and the agent registry."""

from datetime import datetime
from typing import Any
from app.services.ai.schemas import UsageStatsResponse
from app.core.log import logger
from fastapi import (
    APIRouter,
    HTTPException,
)
from pydantic import BaseModel

from app.components.backend.api.ai.service import ai_service

router = APIRouter()


@router.get("/usage/stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    user_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    recent_limit: int = 10,
) -> UsageStatsResponse:
    """
    Get aggregated LLM usage statistics.

    All aggregations are performed at the SQL level for scalability.
    Supports filtering by user and time range.

    Args:
        user_id: Optional filter by user
        start_time: Optional start of time range (ISO format)
        end_time: Optional end of time range (ISO format)
        recent_limit: Number of recent activities to return (default: 10)

    Returns:
        Usage statistics including totals, model breakdown, and recent activity
    """
    try:
        stats = await ai_service.get_usage_stats(
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            recent_limit=recent_limit,
        )
        return UsageStatsResponse(**stats)

    except Exception as e:
        logger.exception("Failed to get usage stats")
        raise HTTPException(
            status_code=500, detail="Failed to get usage stats"
        ) from e


@router.get("/sentiment/stats")
async def get_sentiment_stats() -> dict[str, Any]:
    """
    Get aggregated conversation sentiment statistics.

    Returns the sentiment/performance distributions, average score, and
    the most recent negative conversations, plus whether the scoring job
    is enabled. Zero-filled when nothing has been scored yet.
    """
    from app.services.ai.domains.chat.sentiment import sentiment_stats

    try:
        return await sentiment_stats()
    except Exception as e:
        logger.exception("Failed to get sentiment stats")
        raise HTTPException(
            status_code=500, detail="Failed to get sentiment stats"
        ) from e


class AgentUpdateRequest(BaseModel):
    """Partial update of an agent's editable fields."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    model_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    is_active: bool | None = None


@router.get("/agents")
async def list_registry_agents() -> list[dict[str, Any]]:
    """List all agents in the registry with their tool/module grants."""
    from app.services.ai.domains.chat.agent_registry import list_agents, serialize_agent

    try:
        return [serialize_agent(agent) for agent in await list_agents()]
    except Exception as e:
        logger.exception("Failed to list agents")
        raise HTTPException(status_code=500, detail="Failed to list agents") from e


@router.patch("/agents/{slug}")
async def update_registry_agent(
    slug: str, request: AgentUpdateRequest
) -> dict[str, Any]:
    """Apply a partial agent update (invalidates its cached config)."""
    from app.services.ai.domains.chat.agent_registry import (
        AgentNotFoundError,
        InvalidAgentUpdateError,
        serialize_agent,
        update_agent,
    )

    changes = request.model_dump(exclude_unset=True)
    try:
        agent = await update_agent(slug, changes)
    except AgentNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Agent '{slug}' not found"
        ) from None
    except InvalidAgentUpdateError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("Failed to update agent")
        raise HTTPException(status_code=500, detail="Failed to update agent") from e
    return serialize_agent(agent)
