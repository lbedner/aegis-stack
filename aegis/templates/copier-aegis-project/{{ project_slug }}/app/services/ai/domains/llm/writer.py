"""One agent writing once (``writer``): its row's prompt and model, a typed
answer and no tools: a job's writer, not a chat. While the row is missing or
off, the prompt it is given runs on the model in force. The meetings' notes
and the patterns review write this way."""

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
