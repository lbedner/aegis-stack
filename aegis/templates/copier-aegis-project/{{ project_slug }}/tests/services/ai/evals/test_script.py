"""A case's script: a turn played without a model, free and repeatable."""

from pydantic_ai import Agent
import pytest

from app.services.ai.domains.evals.script import Step, recorded, scripted_model
from app.services.ai.domains.llm.agents import MODEL_OVERRIDE, get_agent
from app.services.ai.domains.llm.config import AIServiceConfig
from app.services.ai.service.trace import TRACE_CODE_CAP


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


def test_a_real_turn_is_recorded_as_the_script_it_took() -> None:
    trace = [
        {"tool": "run_code", "code": "found = await health()\nfound", "nested": [{"tool": "health"}]},
        {"tool": "errors", "args": '{"service": "worker"}', "result": "none"},
    ]

    assert recorded(trace, "All healthy.") == [
        Step(tool="run_code", args={"code": "found = await health()\nfound"}),
        Step(tool="errors", args={"service": "worker"}),
        Step(text="All healthy."),
    ]


@pytest.mark.parametrize(
    "entry",
    [
        {"tool": "errors", "args": '{"text": "a very long te'},
        {"tool": "run_code", "code": "x" * TRACE_CODE_CAP},
    ],
)
def test_a_call_the_trace_clipped_is_not_recorded(entry: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        recorded([entry], "x")
