"""Running a dataset: each case one real turn (``AIService.chat``, the
agent, tools, context and persona chat builds), scored on its reply and the
trace the reply keeps. Keeping the run is its caller's, with a session of
its own (``recorder.record_run``): a run is minutes of model calls."""

from pathlib import Path

from pydantic_evals import set_eval_attribute
from pydantic_evals.reporting import EvaluationReport

from app.core.config import settings
from app.services.ai.domains.chat.agent_loader import CODE_MODE_OVERRIDE
from app.services.ai.domains.llm.agents import MODEL_OVERRIDE
from app.services.ai.service import AIService
from app.services.ai.service.turn import HEARS_NOW
from app.services.system.jobs import Report

from .datasets import EVALS_DIR, CaseInput, CaseMeta, fingerprint, load, without
from .evaluators import (
    CONVERSATION,
    COST,
    EVALS_USER,
    FINGERPRINT,
    GRADED,
    MODEL,
    SPANS,
    TRACE,
)
from .script import in_code_mode, scripted_model


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
) -> EvaluationReport[CaseInput, str, CaseMeta]:
    """Every case of ``name``, one at a time: a real model costs money and
    shares a rate limit. ``scripted`` plays each case's script instead,
    without the checks a model grades or that read spans (no model plays a
    script, and no span is kept), a case left with none failing;
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
    if scripted:
        without(dataset, (*GRADED, *SPANS))
    # Each case's inputs reach the task as the same object, so the case is
    # found by identity: the task is handed only the inputs.
    cases = {id(case.inputs): case for case in dataset.cases}
    started = 0

    async def turn(case: CaseInput) -> str:
        nonlocal started
        started += 1
        if report is not None:
            report(f"{started} of {len(cases)} · {cases[id(case)].name}")
        if scripted and not case.script:
            raise ValueError("this case has no script to play")
        if scripted and not (cases[id(case)].evaluators or dataset.evaluators):
            raise ValueError("this case has no check a script can be held to")
        token = MODEL_OVERRIDE.set(scripted_model(case.script) if scripted else None)
        mode = CODE_MODE_OVERRIDE.set(in_code_mode(case.script) if scripted else None)
        told = HEARS_NOW.set(False)
        try:
            # An admin's turn: only an admin starts a run (the evals API's gate).
            reply = await service.chat(
                case.message,
                user_id=EVALS_USER,
                agent_slug=case.agent,
                surface="evals",
                admin=True,
            )
        finally:
            MODEL_OVERRIDE.reset(token)
            CODE_MODE_OVERRIDE.reset(mode)
            HEARS_NOW.reset(told)
        for key in (TRACE, CONVERSATION, COST, MODEL):
            set_eval_attribute(key, reply.metadata.get(key))
        return reply.content

    return await dataset.evaluate(
        turn,
        name=name,
        max_concurrency=1,
        progress=False,
        metadata={FINGERPRINT: fingerprint(name, directory)},
    )
