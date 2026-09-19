"""The redis keys, and turning a task into something readable."""

from typing import Any

_TASK_KEY_PREFIX = "aegis:task:"
_QUEUE_INDEX_PREFIX = "aegis:tasks:queue:"


def resolve_task_docstring(task_name: str) -> str:
    """Look up a task function's docstring from the registry.

    Returns the first line of the docstring, or an empty string.
    """
    try:
        from app.components.worker.tasks import get_task_by_name

        func = get_task_by_name(task_name)
        if func and func.__doc__:
            # Return first non-empty line of the docstring
            for line in func.__doc__.strip().splitlines():
                stripped = line.strip()
                if stripped:
                    return stripped
    except Exception:
        pass
    return ""


def _enrich_mapping(mapping: dict[str, str], task_name: str | None) -> None:
    """Add task name and docstring to a mapping if available."""
    if task_name:
        mapping["name"] = task_name
        doc = resolve_task_docstring(task_name)
        if doc:
            mapping["description"] = doc


async def resolve_arq_task_name(redis: Any, job_id: str) -> str | None:
    """Extract function name for an arq job.

    Tries the job key first (available during/before execution),
    then falls back to the result key (available after execution).
    arq's hooks don't include the function name in ``ctx``, so we
    read it directly from Redis.
    """
    try:
        from arq.constants import job_key_prefix, result_key_prefix
        from arq.jobs import deserialize_job_raw, deserialize_result

        # Try job key first (still exists during on_job_start)
        raw = await redis.get(job_key_prefix + job_id)
        if raw:
            function_name, *_ = deserialize_job_raw(raw)
            return function_name

        # Fall back to result key (exists after job completes)
        raw = await redis.get(result_key_prefix + job_id)
        if raw:
            result = deserialize_result(raw)
            return result.function  # type: ignore[return-value]
    except Exception:
        pass
    return None
