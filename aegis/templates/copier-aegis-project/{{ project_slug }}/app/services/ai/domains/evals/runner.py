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
    name: str, *, scripted: bool = False, directory: Path = EVALS_DIR
) -> EvaluationReport[CaseInput, str, None]:
    """Every case of ``name``, one at a time: a real model costs money and
    shares a rate limit. ``scripted`` plays each case's script instead."""
    _observe()
    service = AIService(settings)

    async def turn(case: CaseInput) -> str:
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

    dataset = load(name, directory)
    return await dataset.evaluate(turn, name=name, max_concurrency=1, progress=False)
