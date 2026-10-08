"""The Overseer Worker page's action: start a load test. Mounted by
``routes/pages.py`` behind Overseer's gate."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.components.web_frontend import overseer_worker_load_tests as load_tests
from app.components.web_frontend.rendering import form_fields, toast_response

router = APIRouter(prefix=load_tests.PARTIALS)


@router.post("/load-tests")
async def start_load_test(request: Request) -> Response:
    """Start a run; the list picks it up over its stream."""
    test_id, why = await load_tests.start(await form_fields(request))
    if test_id is None:
        return toast_response(f"Load test not started: {why}", "error")
    return toast_response(f"Load test {test_id} started")
