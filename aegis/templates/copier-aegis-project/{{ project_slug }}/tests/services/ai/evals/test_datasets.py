"""Datasets kept in the database: added from YAML and read back as written,
what each says it is and checks in words, deleted, and the shipped files
seeded where missing."""

from pathlib import Path

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.evals.datasets import (
    UnknownDatasetError,
    add,
    add_file,
    describe,
    describe_all,
    fingerprint,
    names,
    remove,
    seed_missing,
    text,
)
from app.services.ai.models.evals import EvalDatasetRecord

from ._mini import DATASET

# Each test reads back, by name, what it kept: the store is what is under test.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


async def test_a_dataset_is_read_back_as_it_was_written(
    async_db_session: AsyncSession,
) -> None:
    written = "# Reads what it is given.\n" + DATASET
    kept = await add(async_db_session, "mini", written)

    assert await names(async_db_session) == ["mini"]
    assert await text(async_db_session, "mini") == written
    assert kept == await describe(async_db_session, "mini")
    assert kept.about == "Reads what it is given." and len(kept.cases) == 2
    assert fingerprint(written) == fingerprint(written) != fingerprint(DATASET)


async def test_a_dataset_says_what_it_is_and_what_each_case_checks(
    async_db_session: AsyncSession,
) -> None:
    about = "# Reads what it is given.\n# Two cases.\n#\n# How to add one.\n"
    shared = "evaluators:\n  - AnswerAvoids:\n      terms: [sorry]\n"
    await add(async_db_session, "mini", about + DATASET + shared)

    found = await describe(async_db_session, "mini")

    assert found.name == "mini" and found.about == "Reads what it is given. Two cases."
    first, second = found.cases
    assert first.name == "reads the paper"
    assert first.message == "what does the letter say?" and first.agent is None
    assert first.checks == ["calls paper once", 'says "letter"', 'never says "sorry"']
    assert second.checks == ["never calls delete", 'never says "sorry"']
    assert first.why is None


async def test_a_case_says_why_it_is_there(async_db_session: AsyncSession) -> None:
    why = "    metadata:\n      why: a letter is read, not guessed\n"
    marked = DATASET.replace("    evaluators:\n", why + "    evaluators:\n", 1)
    await add(async_db_session, "mini", marked)

    first, second = (await describe(async_db_session, "mini")).cases

    assert (first.why, second.why) == ("a letter is read, not guessed", None)


@pytest.mark.parametrize(
    ("name", "written", "why"),
    [
        ("../mini", DATASET, "not a dataset name"),
        ("Mini", DATASET, "not a dataset name"),
        ("torn", "cases: [", "not YAML"),
        ("wrong", "cases:\n  - name: x\n    inputs: {nope: 1}\n", "inputs"),
        ("retired", DATASET.replace("ToolCalls", "Retired"), "'Retired' is not"),
    ],
)
async def test_what_cannot_be_a_dataset_is_refused(
    async_db_session: AsyncSession, name: str, written: str, why: str
) -> None:
    with pytest.raises(ValueError, match=why):
        await add(async_db_session, name, written)

    assert await names(async_db_session) == []


async def test_a_name_is_taken_once_unless_replaced(
    async_db_session: AsyncSession,
) -> None:
    await add(async_db_session, "mini", DATASET)

    with pytest.raises(ValueError, match="already exists"):
        await add(async_db_session, "mini", DATASET)
    await add(async_db_session, "mini", "# Edited.\n" + DATASET, replace=True)
    assert (await describe(async_db_session, "mini")).about == "Edited."


async def test_a_dataset_is_deleted_and_its_name_is_free_again(
    async_db_session: AsyncSession,
) -> None:
    await add(async_db_session, "mini", DATASET)

    await remove(async_db_session, "mini")

    assert await names(async_db_session) == []
    for read in (text, describe, remove):
        with pytest.raises(UnknownDatasetError, match="mini"):
            await read(async_db_session, "mini")
    await add(async_db_session, "mini", "# Again.\n" + DATASET)
    assert (await describe(async_db_session, "mini")).about == "Again."


async def test_a_row_that_cannot_be_read_hides_no_other(
    async_db_session: AsyncSession,
) -> None:
    """Written before a check it names went away: listed with why, the rest
    read as ever, and still deleted."""
    retired = DATASET.replace("ToolCalls", "Retired")
    async_db_session.add(EvalDatasetRecord(name="gone", text=retired))
    await add(async_db_session, "mini", DATASET)

    gone, mini = await describe_all(async_db_session)

    assert gone.about.startswith("Cannot be read") and gone.cases == []
    assert len(mini.cases) == 2
    await remove(async_db_session, "gone")


async def test_shipped_files_are_seeded_once_and_never_over_the_apps_own(
    async_db_session: AsyncSession, tmp_path: Path
) -> None:
    """The seed adds a name this database has never had; one deleted in
    the app stays deleted."""
    (tmp_path / "mini.yaml").write_text(DATASET)
    (tmp_path / "other.yaml").write_text(DATASET)

    assert await seed_missing(async_db_session, tmp_path) == 2
    await remove(async_db_session, "other")
    (tmp_path / "later.yaml").write_text(DATASET)

    assert await seed_missing(async_db_session, tmp_path) == 1
    assert await names(async_db_session) == ["later", "mini"]


async def test_an_edited_shipped_file_reaches_its_row_unless_the_app_changed_it(
    async_db_session: AsyncSession, tmp_path: Path
) -> None:
    """A row still as it was seeded follows its file; one edited, deleted
    or imported in the app stays as it is."""
    for name in ("follows", "edited", "deleted"):
        (tmp_path / f"{name}.yaml").write_text(DATASET)
    await add(async_db_session, "imported", DATASET)
    (tmp_path / "imported.yaml").write_text(DATASET)
    assert await seed_missing(async_db_session, tmp_path) == 3
    await add(async_db_session, "edited", "# Mine.\n" + DATASET, replace=True)
    await remove(async_db_session, "deleted")
    for name in ("follows", "edited", "deleted", "imported"):
        (tmp_path / f"{name}.yaml").write_text("# Shipped again.\n" + DATASET)

    assert await seed_missing(async_db_session, tmp_path) == 1

    assert (await describe(async_db_session, "follows")).about == "Shipped again."
    assert (await describe(async_db_session, "edited")).about == "Mine."
    assert (await describe(async_db_session, "imported")).about == ""
    assert await names(async_db_session) == ["edited", "follows", "imported"]
    assert await seed_missing(async_db_session, tmp_path) == 0


async def test_a_shipped_file_that_cannot_be_read_hides_no_other(
    async_db_session: AsyncSession, tmp_path: Path
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    (tmp_path / "torn.yaml").write_text("cases: [")

    assert await seed_missing(async_db_session, tmp_path) == 1
    assert await names(async_db_session) == ["mini"]


@pytest.mark.parametrize("filename", ["ops.yaml", "ops.yml", "evals/ops.yaml"])
async def test_a_file_is_kept_as_the_dataset_its_name_says(
    async_db_session: AsyncSession, filename: str
) -> None:
    assert await add_file(async_db_session, filename, DATASET.encode()) == "ops"
    assert await text(async_db_session, "ops") == DATASET


async def test_a_file_that_is_not_text_is_refused(async_db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="not text"):
        await add_file(async_db_session, "ops.yaml", b"\xff\xfe")
