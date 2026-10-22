"""One agent writing once (``writer``): its row's prompt and model, a typed
answer and no tools: a job's writer, not a chat. While the row is missing or
off, the prompt it is given runs on the model in force. ``write`` runs one
over a text and meters it. The meetings' notes and the patterns review
write this way."""

from typing import TypeVar

from pydantic_ai import Agent

from app.core.config import settings
from app.services.ai.domains.llm import active_model

Output = TypeVar("Output")


async def writer(
    slug: str, prompt: str, output_type: type[Output]
) -> tuple[Agent[None, Output], str]:
    """The agent ``slug`` writes with (``prompt`` while it has no row),
    and the name of the model it runs on."""
    # Here, not at the top: the factory loads every provider's SDK, which
    # only a writer at work needs.
    from app.services.ai.domains.llm import model_factory

    config, instructions = await active_model.agent_in_force(settings, slug, prompt)
    model, model_name = await model_factory.model_for(config, settings)
    agent = Agent(
        model,
        instructions=instructions,
        output_type=output_type,
        model_settings=model_factory._model_settings(config),
        name=slug,
    )
    return agent, model_name


async def write(
    slug: str,
    prompt: str,
    output_type: type[Output],
    text: str,
    *,
    action: str,
    owner_user_id: int | None,
) -> tuple[Output, str]:
    """One pass of the agent ``slug`` (``writer``) over ``text``, metered as
    ``action`` against the owner: what it wrote, and the model's name."""
    # Here, not at the top: what meters it lives with the stack's spend,
    # read only by a writer at work.
    from app.services.ai.domains.spend.recording import extract_usage, record_usage

    agent, model_name = await writer(slug, prompt, output_type)
    result = await agent.run(text)
    await record_usage(
        action=action,
        model_name=model_name,
        usage=extract_usage(result),
        user_id=None if owner_user_id is None else str(owner_user_id),
    )
    return result.output, model_name
