"""Running a dataset: each case one real turn (``AIService.chat``, the
agent, tools, context and persona chat builds), scored on its reply and the
trace the reply keeps. Keeping the run is its caller's, with a session of
its own (``recorder.record_run``): a run is minutes of model calls."""

from pathlib import Path

from pydantic_evals import set_eval_attribute
from pydantic_evals.reporting import EvaluationReport

from app.core.config import settings
from app.services.ai.domains.llm.agents import MODEL_OVERRIDE
from app.services.ai.service import AIService
from app.services.system.jobs import Report

from .datasets import EVALS_DIR, CaseInput, load
from .evaluators import CONVERSATION, COST, EVALS_USER, MODEL, TRACE
from .script import scripted_model


def _observe() -> None:
    """Report the run to Logfire as its own process, where the stack has
    observability; with no token, ``configure_logfire`` does nothing."""
    try:
        from app.components.backend.middleware.logfire_tracing import (
            configure_logfire,
        )
    except ImportError:  # observability component not installed
        return
    configure_logfire("evals")


async def run_dataset(
    name: str,
    *,
    scripted: bool = False,
    model: str | None = None,
    provider: str | None = None,
    report: Report | None = None,
    directory: Path = EVALS_DIR,
) -> EvaluationReport[CaseInput, str, None]:
    """Every case of ``name``, one at a time: a real model costs money and
    shares a rate limit. ``scripted`` plays each case's script instead;
    ``model`` (on ``provider``, where it needs another) stands in for the
    configured one where an agent pins none; ``report`` hears each case as
    it starts."""
    _observe()
    in_force = settings
    if model:
        provider = provider or settings.AI_PROVIDER
        in_force = settings.model_copy(update={"AI_MODEL": model, "AI_PROVIDER": provider})
    service = AIService(in_force)
    dataset = load(name, directory)
    # Each case's inputs reach the task as the same object, so its name is
    # found by identity: the task is handed only the inputs.
    named = {id(case.inputs): case.name for case in dataset.cases}
    started = 0

    async def turn(case: CaseInput) -> str:
        nonlocal started
        started += 1
        if report is not None:
            report(f"{started} of {len(named)} · {named[id(case)]}")
        if scripted and not case.script:
            raise ValueError("this case has no script to play")
        token = MODEL_OVERRIDE.set(scripted_model(case.script) if scripted else None)
        try:
            reply = await service.chat(
                case.message, user_id=EVALS_USER, agent_slug=case.agent, surface="evals"
            )
        finally:
            MODEL_OVERRIDE.reset(token)
        for key in (TRACE, CONVERSATION, COST, MODEL):
            set_eval_attribute(key, reply.metadata.get(key))
        return reply.content

    return await dataset.evaluate(turn, name=name, max_concurrency=1, progress=False)
