"""An eval run, and a dataset written by the model, as worker tasks (arq
form): each case lands in the shared job store as it starts. The AI
service is imported lazily: a worker stack without evals still imports
this module and never receives the task."""

from typing import Any


async def run_evals_task(
    ctx: dict[str, Any], job_id: str, name: str, model: str | None, note: str | None
) -> dict[str, Any]:
    from app.services.ai.service import run_evals_job

    return await run_evals_job(job_id, name, model, note)


async def generate_evals_task(
    ctx: dict[str, Any], job_id: str, name: str, about: str, cases: int, like: str | None
) -> dict[str, Any]:
    from app.services.ai.service import generate_evals_job

    return await generate_evals_job(job_id, name, about, cases, like)
