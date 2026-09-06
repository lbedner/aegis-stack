"""The reference seed has to survive the session the startup hook uses.

Currencies and CSV import profiles are seeded on boot so a fresh install
can import a Chase or AMEX file immediately. The profile rows carry a
currency, and that currency is a foreign key, so the currency rows have
to be in the database before the profiles are written.

Adding both to one session and committing once is not enough. The app's
sync session factory is built with ``autoflush=False``, so nothing
reaches the database until the commit, and the insert order chosen then
does not put the currencies first: the key points at ``code``, which is
not the primary key, so the dependency is invisible to the sort. On a
fresh database the whole seed rolled back with a foreign-key error, and
the startup hook logged it as a warning and carried on - leaving an
install with no import profiles and no obvious reason why.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, select

from app.services.finance.models import FinanceCurrency, FinanceImportProfile
from app.services.finance.seeds.seed import seed_finance_tables


@pytest.fixture
def startup_session(engine: Engine) -> Generator[Session]:
    """A session shaped like the one the startup hook actually uses.

    The shared ``db_session`` fixture autoflushes, which hides the bug
    entirely: the SELECT before each profile would push the currencies
    out first. ``app/core/db.py`` builds its sync factory with
    ``autoflush=False``, so the seed has to be correct without that help.
    """
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        class_=Session, bind=connection, autoflush=False, autocommit=False
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_a_fresh_database_gets_its_import_profiles(startup_session: Session) -> None:
    seed_finance_tables(startup_session)

    profiles = startup_session.exec(select(FinanceImportProfile)).all()

    assert profiles, "a fresh install has no CSV import profiles"


def test_the_currencies_the_profiles_reference_are_there_too(
    startup_session: Session,
) -> None:
    seed_finance_tables(startup_session)

    codes = {c.code for c in startup_session.exec(select(FinanceCurrency)).all()}
    used = {
        p.currency for p in startup_session.exec(select(FinanceImportProfile)).all()
    }

    assert used <= codes, (
        f"profiles reference currencies never seeded: {used - codes}"
    )


def test_seeding_twice_changes_nothing(startup_session: Session) -> None:
    """The hook runs on every boot."""
    seed_finance_tables(startup_session)
    first = len(startup_session.exec(select(FinanceImportProfile)).all())

    seed_finance_tables(startup_session)
    second = len(startup_session.exec(select(FinanceImportProfile)).all())

    assert first == second
