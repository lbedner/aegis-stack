"""Running a dataset: each case one real turn (``AIService.chat``, the
agent, tools, context and persona chat builds), scored on its reply and the
trace the reply keeps."""

from pathlib import Path

from pydantic_evals import set_eval_attribute
from pydantic_evals.reporting import EvaluationReport

from app.core.config import settings
from app.services.ai.domains.llm.agents import MODEL_OVERRIDE
from app.services.ai.service import AIService

from .datasets import EVALS_DIR, CaseInput, load
from .evaluators import TRACE
from .script import scripted_model

# Whose conversations an eval run's turns are, so they never mix with a person's.
EVALS_USER = "evals"


async def run_dataset(
    name: str, *, scripted: bool = False, directory: Path = EVALS_DIR
) -> EvaluationReport[CaseInput, str, None]:
    """Every case of ``name``, one at a time: a real model costs money and
    shares a rate limit. ``scripted`` plays each case's script instead."""
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
        set_eval_attribute(TRACE, reply.metadata.get(TRACE, []))
        return reply.content

    dataset = load(name, directory)
    return await dataset.evaluate(turn, name=name, max_concurrency=1, progress=False)
