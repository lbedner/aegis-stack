"""A case's script: a turn played without a model, free and repeatable."""

from pydantic_ai import Agent

from app.services.ai.domains.evals.script import Step, scripted_model
from app.services.ai.domains.llm.agents import MODEL_OVERRIDE, get_agent
from app.services.ai.domains.llm.config import AIServiceConfig


async def test_a_script_calls_its_tools_then_answers() -> None:
    seen: list[int] = []

    async def lookup(key: str) -> str:
        """Look a key up."""
        seen.append(len(key))
        return "found"

    model = scripted_model(
        [Step(tool="lookup", args={"key": "abc"}), Step(text="It was found.")]
    )
    agent = Agent(model, tools=[lookup])

    streamed = []
    async with agent.run_stream_events("go") as events:
        async for event in events:
            streamed.append(type(event).__name__)
    assert seen == [3]
    assert "FunctionToolCallEvent" in streamed


async def test_an_override_model_answers_for_every_agent_built() -> None:
    model = scripted_model([Step(text="scripted")])
    token = MODEL_OVERRIDE.set(model)
    try:
        agent = await get_agent(AIServiceConfig(), settings=None)
    finally:
        MODEL_OVERRIDE.reset(token)
    assert agent.model is model
