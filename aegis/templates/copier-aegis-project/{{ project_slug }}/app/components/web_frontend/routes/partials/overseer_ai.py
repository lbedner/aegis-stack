"""Fragments for the Overseer AI page: each provider's logo from the
catalog's org marks, a catalog model in the drawer, making a model the
active one, an agent's definition in the drawer and saved, a memory
module's editor and preview, correcting or forgetting a saved fact, and
the RAG index: a collection's files, deleting it, and a search; and an
audio file transcribed. Mounted by ``routes/pages.py``."""

from typing import Annotated, Any

from app.components.web_frontend import (
    overseer_ai_agents,
    overseer_ai_catalog,
    overseer_ai_rag,
    overseer_ai_voice,
)
from app.components.web_frontend.chat_surface import HAS_VOICE, PERSISTED
from app.components.web_frontend.overseer_access import Db, overseer_db
from app.components.web_frontend.overseer_ai_common import HAS_RAG, PARTIALS
from app.components.web_frontend.rendering import (
    dialog,
    form_fields,
    go_to,
    image_response,
    toast_response,
)
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

router = APIRouter(prefix=PARTIALS)
# What the stack has decides what is mounted (at the end): a database for
# the catalog, agents, memory modules and saved facts; RAG for its
# collections and search; voice for transcription. A route for something
# the stack lacks is not there (a 404), never a crash.
stored = APIRouter()
with_rag = APIRouter()
with_voice = APIRouter()


@stored.get("/icons/{slug}")
async def provider_icon(
    request: Request,
    slug: str,
    db: Db = Depends(overseer_db),
) -> Response:
    """A provider's mark, for the browser to cache; the page only links to
    one the catalog holds, so a 404 here is a mark since removed."""
    from app.services.ai.domains.llm.queries import org_icons

    icon = (await org_icons(db, [slug])).get(slug)
    if icon is None:
        raise HTTPException(status_code=404)
    return image_response(request, icon)


@stored.get("/models/drawer", response_class=HTMLResponse)
async def model_drawer(
    request: Request,
    model: str,
) -> Response:
    context = await overseer_ai_catalog.model_context(model)
    if context is None:
        raise HTTPException(status_code=404, detail="That model is not in the catalog.")
    return dialog(request, "pages/overseer/ai/_model_drawer.html", **context)


async def set_active_model(model_id: str, force: bool = False) -> Any:
    """The catalog's switch (a persistence backend's module): stored, and
    live for the next request."""
    from app.services.ai.domains.llm.llm_service import set_active_model as switch

    return await switch(model_id, force=force)


@stored.post("/models/use")
async def use_model(
    model_id: Annotated[str, Form()] = "",
) -> Response:
    """Make ``model_id`` the model the app answers with."""
    result = await set_active_model(model_id)
    if not result.success:
        return toast_response(result.message, "error")
    return go_to(
        overseer_ai_catalog.model_url(model_id), result.message, target="#overseer-main"
    )


@stored.get("/agents/{slug}/drawer", response_class=HTMLResponse)
async def agent_drawer(
    request: Request,
    slug: str,
    db: Db = Depends(overseer_db),
) -> Response:
    context = await overseer_ai_agents.agent_context(db, slug)
    if context is None:
        raise HTTPException(status_code=404, detail="No such agent.")
    return dialog(request, "pages/overseer/ai/_agent_drawer.html", **context)


async def update_agent(db: Db, slug: str, changes: dict[str, Any]) -> Any:
    """The registry's update (validates, saves, drops the cached config)."""
    from app.services.ai.domains.chat.agent_registry import update_agent as update

    return await update(slug, changes, session=db)


@stored.post("/agents/{slug}")
async def save_agent(
    request: Request,
    slug: str,
    db: Db = Depends(overseer_db),
) -> Response:
    """Save the drawer's editor. A value the registry refuses is the toast."""
    form = await form_fields(request)
    try:
        changes = overseer_ai_agents.parse_agent_form(form)
        agent = await update_agent(db, slug, changes)
    except ValueError as exc:  # the registry's errors are ValueErrors too
        return toast_response(str(exc), "error")
    if form.get("stay"):  # opened from a chat reply: stay in the thread
        return toast_response(f"Saved {agent.name}")
    return go_to(
        overseer_ai_agents.agents_url(agent=slug),
        f"Saved {agent.name}",
        target="#overseer-main",
    )


@stored.get("/modules/{slug}/drawer", response_class=HTMLResponse)
async def module_drawer(
    request: Request,
    slug: str,
    db: Db = Depends(overseer_db),
) -> Response:
    context = await overseer_ai_agents.module_context(db, slug)
    if context is None:
        raise HTTPException(status_code=404, detail="No such memory module.")
    return dialog(request, "pages/overseer/ai/_module_drawer.html", **context)


async def update_module(db: Db, slug: str, changes: dict[str, Any]) -> Any:
    """The module registry's update (keeps the content invariant)."""
    from app.services.ai.domains.chat.memory_modules import update_memory_module

    return await update_memory_module(slug, session=db, **changes)


@stored.post("/modules/{slug}")
async def save_module(
    request: Request,
    slug: str,
    db: Db = Depends(overseer_db),
) -> Response:
    module = await overseer_ai_agents.module_row(db, slug)
    if module is None:
        raise HTTPException(status_code=404, detail="No such memory module.")
    form = await form_fields(request)
    try:
        changes = overseer_ai_agents.parse_module_form(
            form, static=not module.get("fetch_function")
        )
        saved = await update_module(db, slug, changes)
    except ValueError as exc:  # the registry's refusals are ValueErrors
        return toast_response(str(exc), "error")
    return go_to(
        overseer_ai_agents.memory_url(module=slug),
        f"Saved {saved.name}",
        target="#overseer-main",
    )


async def _fact(db: Db, index: int) -> dict[str, Any]:
    facts = await overseer_ai_agents.fact_rows(db)
    fact = next((f for f in facts if f["index"] == index), None)
    if fact is None:
        raise HTTPException(status_code=404, detail="That fact is gone.")
    return fact


@stored.get("/facts/{index}/edit", response_class=HTMLResponse)
async def fact_form(
    request: Request,
    index: int,
    db: Db = Depends(overseer_db),
) -> Response:
    return dialog(
        request,
        "pages/overseer/ai/_fact_edit.html",
        fact=await _fact(db, index),
        url=f"{PARTIALS}/facts/{index}",
    )


async def correct_fact(db: Db, index: int, fact: str, category: str) -> Any:
    from app.services.ai.domains.chat.user_memory import (
        DEFAULT_MEMORY_USER_ID,
        update_user_fact,
    )

    return await update_user_fact(
        DEFAULT_MEMORY_USER_ID, index, fact=fact, category=category, session=db
    )


@stored.post("/facts/{index}")
async def save_fact(
    index: int,
    fact: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "general",
    db: Db = Depends(overseer_db),
) -> Response:
    if not fact.strip():
        return toast_response("A fact needs words; forget it instead.", "error")
    try:
        await correct_fact(db, index, fact.strip(), category.strip() or "general")
    except IndexError:
        raise HTTPException(status_code=404, detail="That fact is gone.") from None
    return go_to(
        overseer_ai_agents.memory_url(), "Fact corrected", target="#overseer-main"
    )


@stored.get("/facts/{index}/confirm-forget", response_class=HTMLResponse)
async def confirm_forget(
    request: Request,
    index: int,
    db: Db = Depends(overseer_db),
) -> Response:
    fact = await _fact(db, index)
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title="Forget this fact?",
        body=fact["fact"],
        url=f"{PARTIALS}/facts/{index}",
        label="Forget",
        method="delete",
        done="Fact forgotten",
    )


async def forget_fact(db: Db, index: int) -> Any:
    from app.services.ai.domains.chat.user_memory import (
        DEFAULT_MEMORY_USER_ID,
        delete_user_fact,
    )

    return await delete_user_fact(DEFAULT_MEMORY_USER_ID, index, session=db)


@stored.delete("/facts/{index}", status_code=204)
async def forget(
    index: int,
    db: Db = Depends(overseer_db),
) -> Response:
    try:
        await forget_fact(db, index)
    except IndexError:
        raise HTTPException(status_code=404, detail="That fact is gone.") from None
    return Response(status_code=204)


@with_rag.get("/collections/{name}/drawer", response_class=HTMLResponse)
async def collection_drawer(request: Request, name: str) -> Response:
    context = await overseer_ai_rag.collection_context(name)
    if context is None:
        raise HTTPException(status_code=404, detail="No such collection.")
    return dialog(request, "pages/overseer/ai/_collection_drawer.html", **context)


@with_rag.get("/collections/{name}/confirm-delete", response_class=HTMLResponse)
async def confirm_delete_collection(request: Request, name: str) -> Response:
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete {name}?",
        body="Every chunk in it goes; agents stop finding it. The source files stay.",
        url=f"{PARTIALS}/collections/{name}",
        label="Delete",
        method="delete",
        done="Collection deleted",
    )


@with_rag.delete("/collections/{name}", status_code=204)
async def delete_collection(name: str) -> Response:
    if not await overseer_ai_rag.delete_collection(name):
        raise HTTPException(status_code=404, detail="No such collection.")
    return Response(status_code=204)


@with_rag.post("/rag/search", response_class=HTMLResponse)
async def rag_search(
    request: Request,
    collection: Annotated[str, Form()] = "",
    query: Annotated[str, Form()] = "",
    top_k: Annotated[int, Form()] = 5,
) -> Response:
    """The chunks the index returns for ``query``, ranked."""
    if not query.strip():
        return toast_response("Ask the index something.", "error")
    results = await overseer_ai_rag.search(
        query=query.strip(), collection_name=collection, top_k=top_k
    )
    return dialog(
        request,
        "pages/overseer/ai/_search_results.html",
        query=query.strip(),
        rows=overseer_ai_rag.result_rows(results),
    )


@with_voice.post("/voice/transcribe", response_class=HTMLResponse)
async def transcribe(
    request: Request,
    audio: UploadFile,
) -> Response:
    """The file's words, from the speech API's transcription."""
    try:
        result = await overseer_ai_voice.transcribe(audio)
    except HTTPException as exc:  # its format and provider errors
        return toast_response(str(exc.detail), "error")
    return dialog(request, "pages/overseer/ai/_voice_transcript.html", result=result)


for part, present in (
    (stored, PERSISTED),
    (with_rag, HAS_RAG),
    (with_voice, HAS_VOICE),
):
    if present:
        router.include_router(part)
