"""What the app is, whole (``app.core.ontology``), for an operator: the
system model as JSON, for an export or a curl. Behind ``get_admin_actor``
(open on a stack without auth, as every operator route is). Queries are
the MCP tool's (``ontology``), not this route's."""

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.ontology import SystemModel
from app.core.ontology.observed import running
from app.services.shared.deps import get_admin_actor

router = APIRouter(tags=["ontology"])


@router.get(
    "/ontology",
    response_model=SystemModel,  # the schema; the model is valid already
    dependencies=[Depends(get_admin_actor)],
)
async def ontology() -> Response:
    """The model, each edge with what this build has done along it."""
    model = await running()
    return Response(model.model_dump_json(), media_type="application/json")
