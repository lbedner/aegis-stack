"""Datasets, kept in the database (``EvalDatasetRecord``): each its YAML
as written, each case a message and what its turn should do. Pydantic
Evals reads the YAML; a case may use its built-in evaluators (``Contains``,
``LLMJudge``) and the trace ones here. YAML is how a dataset comes in
(``add``, ``add_file``, the shipped ``evals/*.yaml`` by ``seed_missing``)
and goes out (``text``)."""

import hashlib
from pathlib import Path, PurePath
import re

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession
import yaml

from app.core.log import logger
from app.core.source_index import ROOT
from app.core.time import utcnow
from app.services.ai.models.evals import EvalDatasetRecord

from . import queries
from .evaluators import EVALUATORS, explain
from .script import Step

# The datasets the app ships, seeded where missing (``seed_missing``).
EVALS_DIR = ROOT / "evals"
# A dataset's name: what a URL, a file and a CLI argument all carry as is.
# The hyphen is escaped for the form's ``pattern``, which a browser reads too.
NAME = re.compile(r"[a-z0-9][a-z0-9_\-]*")
NAME_HINT = "lowercase letters, digits, - and _"
# What a dataset's YAML is sent as.
YAML_TYPE = "application/yaml"


class CaseInput(BaseModel):
    """What a case asks: a message, to an agent (the default when unset),
    and the ``script`` its turn plays in CI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str
    agent: str | None = None
    script: list[Step] = []


class CaseMeta(BaseModel):
    """What a case says of itself: ``why`` it is there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    why: str | None = None


EvalDataset = Dataset[CaseInput, str, CaseMeta]


class UnknownDatasetError(LookupError, ValueError):
    """A name that is no dataset here."""


def parse(name: str, written: str) -> EvalDataset:
    """``written`` as a dataset, its cases checked against ``CaseInput``;
    ValueError, naming ``name``, for what cannot be read."""
    try:
        return EvalDataset.from_text(
            written, fmt="yaml", default_name=name, custom_evaluator_types=EVALUATORS
        )
    except yaml.YAMLError as exc:
        raise ValueError(f"Dataset {name!r} is not YAML: {exc}") from exc
    except ExceptionGroup as group:  # a check it names that is none here
        raise ValueError(f"Dataset {name!r}: {group.exceptions[0]}") from group


def fingerprint(written: str) -> str:
    """A dataset as written: the SHA-256 of its text."""
    return hashlib.sha256(written.encode()).hexdigest()


def without(dataset: EvalDataset, kinds: tuple[type, ...]) -> None:
    """Drop every check of ``kinds`` from ``dataset`` and its cases."""
    dataset.evaluators = [e for e in dataset.evaluators if not isinstance(e, kinds)]
    for case in dataset.cases:
        case.evaluators = [e for e in case.evaluators if not isinstance(e, kinds)]


class CaseSummary(BaseModel):
    """A case read before a run: what it asks, of which agent (the default
    when unset), and what it checks, in words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    why: str | None = None
    message: str
    agent: str | None
    checks: list[str]


class DatasetSummary(BaseModel):
    """A dataset read before a run: what its leading comment says it is,
    and its cases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    about: str
    cases: list[CaseSummary]


def about(written: str) -> str:
    """A dataset's leading comment, up to its first blank comment line."""
    said: list[str] = []
    for line in written.splitlines():
        if not line.startswith("#") or not line.strip("# "):
            break
        said.append(line.strip("# "))
    return " ".join(said)


def summary(name: str, written: str) -> DatasetSummary:
    """``written`` as ``parse`` reads it, each case's checks its own and
    then the dataset's, which hold for every case."""
    dataset = parse(name, written)
    shared = [explain(e) for e in dataset.evaluators]
    return DatasetSummary(
        name=name,
        about=about(written),
        cases=[
            CaseSummary(
                name=case.name or "",
                why=case.metadata and case.metadata.why,
                message=case.inputs.message,
                agent=case.inputs.agent,
                checks=[*(explain(e) for e in case.evaluators), *shared],
            )
            for case in dataset.cases
        ],
    )


def summed(name: str, written: str) -> DatasetSummary:
    """``summary``; one that cannot be read (a check it names has gone)
    says why where its ``about`` goes, with no cases, so it hides no other
    and can still be opened, exported and deleted."""
    try:
        return summary(name, written)
    except ValueError as exc:
        return DatasetSummary(name=name, about=f"Cannot be read: {exc}", cases=[])


def summaries(kept: dict[str, str]) -> list[DatasetSummary]:
    """Each of ``kept`` (``texts``), ``summed``."""
    return [summed(name, written) for name, written in kept.items()]


async def texts(session: AsyncSession) -> dict[str, str]:
    """Every dataset's YAML as written, by name, in one read."""
    return await queries.dataset_texts(session)


async def names(session: AsyncSession) -> list[str]:
    """Every dataset, by name (its YAML left unread)."""
    return await queries.dataset_names(session)


def unknown(name: str) -> UnknownDatasetError:
    """Why ``name`` cannot be read: there is no such dataset."""
    return UnknownDatasetError(f"No dataset {name!r}")


def taken(name: str) -> ValueError:
    """Why ``name`` cannot be a new dataset: there is one."""
    return ValueError(f"Dataset {name!r} already exists")


def check_name(name: str) -> None:
    """ValueError for a ``name`` that is not one (``NAME``)."""
    if not NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a dataset name: {NAME_HINT}")


def name_of(filename: str) -> str:
    """The dataset a file is: ``ops.yaml`` (or ``ops.yml``) is ``ops``."""
    return PurePath(filename).stem


def _checked(name: str, written: str) -> DatasetSummary:
    """``written`` as dataset ``name`` is kept, summed up; ValueError for a
    name that is not one, or YAML that is no dataset."""
    check_name(name)
    return summary(name, written)


async def _record(session: AsyncSession, name: str) -> EvalDatasetRecord:
    record = await queries.dataset_record(session, name)
    if record is None or record.deleted_at is not None:
        raise unknown(name)
    return record


async def text(session: AsyncSession, name: str) -> str:
    """``name``'s YAML, as it was written (``UnknownDatasetError`` for no
    such dataset)."""
    return (await _record(session, name)).text


async def describe(session: AsyncSession, name: str) -> DatasetSummary:
    """``name``, summed up (``summary``)."""
    return summary(name, await text(session, name))


async def describe_all(session: AsyncSession) -> list[DatasetSummary]:
    """Every dataset, summed up (``summaries``), in one read."""
    return summaries(await texts(session))


async def add(
    session: AsyncSession, name: str, written: str, *, replace: bool = False
) -> DatasetSummary:
    """Keep ``written`` as dataset ``name``, over the one there where
    ``replace``: it, summed up. ValueError for a name that is not one or
    is taken, or YAML that is no dataset. A deleted dataset's name is free
    again."""
    found = _checked(name, written)
    record = await queries.dataset_record(session, name)
    if record is not None and record.deleted_at is None and not replace:
        raise taken(name)
    if record is None:
        record = EvalDatasetRecord(name=name, text=written)
    else:
        record.text, record.created_at, record.deleted_at = written, utcnow(), None
    session.add(record)
    try:
        await session.flush()
    except IntegrityError:  # added meanwhile, by another process
        await session.rollback()  # so a caller can still answer, and commit
        raise taken(name) from None
    return found


async def add_file(
    session: AsyncSession, filename: str, data: bytes, *, replace: bool = False
) -> str:
    """Keep a YAML file as the dataset its name says (``name_of``), as
    ``add`` does: that name. ValueError for a file that is not text too."""
    try:
        written = data.decode()
    except UnicodeDecodeError:
        raise ValueError(f"{filename} is not text") from None
    name = name_of(filename)
    await add(session, name, written, replace=replace)
    return name


async def remove(session: AsyncSession, name: str) -> None:
    """Delete ``name`` (``UnknownDatasetError`` when there is none); its
    kept runs stay, and its row with them (``seed_missing``)."""
    record = await _record(session, name)
    record.deleted_at = utcnow()
    session.add(record)
    await session.flush()


def shipped(directory: Path = EVALS_DIR) -> dict[str, str]:
    """The datasets the app ships, by name (``name_of``): each file's text."""
    return {name_of(path.name): path.read_text() for path in sorted(directory.glob("*.yaml"))}


def _readable(name: str, written: str) -> bool:
    try:
        _checked(name, written)
    except ValueError as exc:
        logger.warning(f"Shipped eval dataset skipped: {exc}")
        return False
    return True


def _as_seeded(row: EvalDatasetRecord, written: str) -> bool:
    """Whether ``row`` was seeded and is still as it was, with its file
    since changed to ``written``."""
    return (
        row.deleted_at is None
        and row.shipped == fingerprint(row.text)
        and row.text != written
    )


async def seed_missing(session: AsyncSession, directory: Path = EVALS_DIR) -> int:
    """Add each shipped dataset (``shipped``) whose name this database has
    never had, bring each one still as seeded up to its file, and say how
    many. One edited, deleted or imported here stays as it is; one that
    cannot be read is skipped, hiding no other; none are written where
    another process seeded them first."""
    rows = {row.name: row for row in await queries.dataset_rows(session)}
    seeded = 0
    for name, written in shipped(directory).items():
        row = rows.get(name)
        if (row is not None and not _as_seeded(row, written)) or not _readable(name, written):
            continue
        row = row or EvalDatasetRecord(name=name, text=written)
        row.text, row.shipped, row.created_at = written, fingerprint(written), utcnow()
        session.add(row)
        seeded += 1
    try:
        await session.flush()
    except IntegrityError as exc:  # two seeding at once (webservers, or ``ai evals``)
        await session.rollback()
        logger.warning(f"Eval datasets seeded elsewhere first: {exc.orig}")
        return 0
    return seeded
