"""A case added to a dataset without its YAML written by hand: said as
fields, or drawn from a turn that happened."""

import json

from pydantic import ValidationError
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.evals.cases import (
    UnknownTurnError,
    add_case,
    calls_from,
    from_turn,
)
from app.services.ai.domains.evals.datasets import (
    UnknownDatasetError,
    add,
    describe,
    parse,
    text,
)
from app.services.ai.domains.evals.script import Step

from ._mini import BALANCE, DATASET, turn

# Each test reads back, by name, what it kept: the store is what is under test.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)

ABOUT = "Reads what it is given."

async def test_a_case_joins_its_dataset(async_db_session: AsyncSession) -> None:
    await add(async_db_session, "mini", f"# {ABOUT}\n{DATASET}")

    found = await add_case(async_db_session, BALANCE)

    assert found == await describe(async_db_session, "mini")
    assert found.about == ABOUT
    first, second, new = found.cases
    assert first.checks == ["calls paper once", 'says "letter"']
    assert second.checks == ["never calls delete"]
    assert (new.name, new.message, new.why) == (
        "a balance is read",
        "what is my balance?",
        "a number is read, never guessed",
    )
    assert new.checks == [
        "calls ledger once",
        "never calls delete",
        'says "balance"',
        'never says "sorry"',
    ]


async def test_a_first_case_makes_its_dataset(async_db_session: AsyncSession) -> None:
    new = BALANCE.model_copy(update={"dataset": "money", "about": "Money is read."})

    found = await add_case(async_db_session, new)

    assert (found.name, found.about, len(found.cases)) == ("money", "Money is read.", 1)
    with pytest.raises(UnknownDatasetError):  # no dataset, and nothing said of one
        await add_case(async_db_session, BALANCE.model_copy(update={"dataset": "other"}))


async def test_a_case_keeps_the_script_its_turn_plays(
    async_db_session: AsyncSession,
) -> None:
    await add(async_db_session, "mini", DATASET)
    script = [Step(tool="ledger", args={"account": 3}), Step(text="Your balance is $5.")]

    await add_case(async_db_session, BALANCE.model_copy(update={"script": script}))

    kept = parse("mini", await text(async_db_session, "mini"))
    assert kept.cases[-1].inputs.script == script
    assert kept.cases[0].inputs.script == []


async def test_a_case_that_cannot_be_kept_says_why(
    async_db_session: AsyncSession,
) -> None:
    await add(async_db_session, "mini", DATASET)
    before = await text(async_db_session, "mini")

    with pytest.raises(ValueError, match="already has a case 'never deletes'"):
        await add_case(
            async_db_session, BALANCE.model_copy(update={"name": "never deletes"})
        )
    nothing = {"calls": {}, "says": [], "avoids": []}
    with pytest.raises(ValueError, match="checks nothing"):
        await add_case(async_db_session, BALANCE.model_copy(update=nothing))

    assert await text(async_db_session, "mini") == before


async def test_a_case_is_drawn_from_a_turn(async_db_session: AsyncSession) -> None:
    args = json.dumps({"name": "letter"})
    trace: list[dict[str, object]] = [
        {"tool": "paper", "args": args, "result": "hello"},
        {"tool": "paper", "args": args, "result": "hello"},
    ]
    answer = await turn(async_db_session, trace)

    drawn = await from_turn(async_db_session, answer.id, "mini")

    assert (drawn.dataset, drawn.message) == ("mini", "what does the letter say?")
    assert drawn.name == "what does the letter say?"
    assert drawn.calls == {"paper": 2}
    call = Step(tool="paper", args={"name": "letter"})
    assert drawn.script == [call, call, Step(text="The letter says hello.")]


async def test_no_such_turn_is_refused(async_db_session: AsyncSession) -> None:
    asked = await turn(async_db_session, [])

    with pytest.raises(UnknownTurnError, match="No turn 'nope'"):
        await from_turn(async_db_session, "nope", "mini")
    with pytest.raises(UnknownTurnError, match="No turn 'q1'"):  # a question is no turn
        await from_turn(async_db_session, "q1", "mini")
    assert (await from_turn(async_db_session, asked.id, "mini")).calls == {}


def test_calls_are_read_as_typed_and_checked() -> None:
    assert calls_from(["ledger", " paper = 2 ", "delete=0"]) == {
        "ledger": 1,
        "paper": 2,
        "delete": 0,
    }
    for odd in ("=2", "ledger=twice", "ledger=-1"):
        with pytest.raises(ValueError, match="a tool, or tool=times"):
            calls_from([odd])
    for unsaid in ({"calls": {"": 1}}, {"calls": {"ledger": -1}}, {"name": ""}):
        with pytest.raises(ValidationError):
            BALANCE.model_validate(BALANCE.model_dump() | unsaid)
