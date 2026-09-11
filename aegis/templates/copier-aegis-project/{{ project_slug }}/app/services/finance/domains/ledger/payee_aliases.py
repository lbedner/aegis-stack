"""The payee memory: what a bank descriptor was taught to mean.

Naming a payee used to be a one-time stamp - ``assign_merchant`` set
merchant_id on the rows in front of you and nothing recorded what the
DESCRIPTOR meant, so the next import offered the same groups again. These
are the other half: written as payees are named, read when an import
creates a transaction.

Its own module rather than more of ``merchants``: that one is the payee
directory (CRUD, merge, the naming backlog), this is the memory of what
naming decided, and they are separately readable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from app.core.time import utcnow
from app.services.finance.domains.ledger import queries
from app.services.finance.models import (
    FinanceMerchantAlias,
    FinanceTransaction,
)
from app.services.finance.utils import transaction_payee_key
from sqlmodel.ext.asyncio.session import AsyncSession


async def _write_payee_aliases(
    db: AsyncSession,
    wanted: dict[str, tuple[int, str, bool]],
    *,
    owner_user_id: int | None = None,
) -> int:
    """Upsert ``key -> (merchant_id, sample, ambiguous)``, returning how
    many keys ended up flagged.

    The one place an alias row is written, so the two callers - naming a
    payee, and rebuilding the whole memory from what is already named -
    cannot drift on what a conflict means. A key is flagged either
    because the caller already knows the history holds two payees, or
    because the row on disk points somewhere else, which is that same
    conflict arriving one naming at a time.
    """
    if not wanted:
        return 0
    existing = await queries.merchant_aliases_by_normalized(
        db, wanted, owner_user_id=owner_user_id
    )
    flagged = 0
    for key, (merchant_id, sample, ambiguous) in wanted.items():
        alias = existing.get(key)
        ambiguous = ambiguous or (
            alias is not None and alias.merchant_id != merchant_id
        )
        flagged += int(ambiguous)
        if alias is None:
            db.add(
                FinanceMerchantAlias(
                    owner_user_id=owner_user_id,
                    merchant_id=merchant_id,
                    alias_text=sample,
                    normalized_alias=key,
                    is_ambiguous=ambiguous,
                    source="user",
                )
            )
        elif alias.merchant_id != merchant_id or alias.is_ambiguous != ambiguous:
            alias.merchant_id = merchant_id
            alias.alias_text = sample
            alias.is_ambiguous = ambiguous
            alias.updated_at = utcnow()
            db.add(alias)
    await db.flush()
    return flagged


def _payee_key_samples(rows: Sequence[FinanceTransaction]) -> dict[str, str]:
    """The distinct payee keys in these rows, each with a descriptor to
    show for it."""
    samples: dict[str, str] = {}
    for txn in rows:
        key = transaction_payee_key(
            txn.merchant_name, txn.original_description, txn.name
        )
        if key:
            samples.setdefault(
                key, txn.merchant_name or txn.original_description or txn.name or ""
            )
    return samples


async def remember_payee_keys(
    db: AsyncSession,
    rows: Sequence[FinanceTransaction],
    merchant_id: int,
    *,
    owner_user_id: int | None = None,
) -> None:
    """Record what each payee key being named MEANS, so the next import
    does not ask again.

    Keyed on ``transaction_payee_key`` - the same four-token grouping the
    user was shown when they named it, which is the point: they confirmed
    a GROUP, so the group is what was taught. Keying on the whole
    descriptor instead was measured against a real ledger and is close to
    useless: one supermarket's 407 rows carried 211 distinct descriptors
    and only 8 prefixes.

    A key taught a SECOND payee is not a correction to apply silently -
    it is a conflict ("NON CHASE ATM WITHDRAW" covered four real payees
    on that ledger). The newest answer is kept, because the user just
    gave it, but the key is flagged and stops resolving unattended from
    then on.
    """
    await _write_payee_aliases(
        db,
        {
            key: (merchant_id, sample, False)
            for key, sample in _payee_key_samples(rows).items()
        },
        owner_user_id=owner_user_id,
    )


async def resolve_merchant_aliases(
    db: AsyncSession,
    descriptors: Iterable[str | None],
    *,
    owner_user_id: int | None = None,
) -> dict[str, int]:
    """descriptor -> payee id for the ones already named unambiguously,
    one query for the whole batch.

    Unmatched descriptors are ABSENT rather than mapped to None, so a
    caller cannot mistake "never taught" for "taught to be nothing". A
    key flagged ambiguous is treated as never taught: the ledger has been
    shown it means two different payees, and naming by hand is better
    than a confident wrong answer.
    """
    by_descriptor = {
        text: transaction_payee_key(None, None, text) for text in descriptors if text
    }
    rows = await queries.merchant_aliases_by_normalized(
        db, by_descriptor.values(), owner_user_id=owner_user_id
    )
    return {
        text: rows[key].merchant_id
        for text, key in by_descriptor.items()
        if key in rows and not rows[key].is_ambiguous
    }


async def recompute_payee_aliases(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> dict[str, int]:
    """Rebuild the payee memory from the transactions already named.

    The alias table is written as payees are named, so it starts empty on
    a ledger whose naming happened before it existed - on a real one,
    11,189 named transactions that would otherwise teach it nothing. This
    reads those namings back.

    Deliberately a recompute rather than a one-off backfill, and it
    answers to the transactions rather than to what it wrote last time:
    running it twice changes nothing, and a payee since cleared drops its
    key instead of leaving the ledger believing an answer the data no
    longer supports. Two things keep bringing the empty-table state back.
    A whole-service restore loads archives written before this table
    existed, and every alias is DERIVED from ``transaction_payee_key``,
    so a change to that key's shape leaves every stored row stale with
    nothing to notice.

    A key that several payees share is flagged from the HISTORY rather
    than waiting to be taught twice, because on a real ledger the
    conflict is already sitting in the data: "NON CHASE ATM WITHDRAW"
    covered four payees there before anybody named anything.
    """
    rows = await queries.named_transactions(db, owner_user_id=owner_user_id)
    merchants_by_key: dict[str, Counter[int]] = {}
    for txn in rows:
        key = transaction_payee_key(
            txn.merchant_name, txn.original_description, txn.name
        )
        if key and txn.merchant_id is not None:
            merchants_by_key.setdefault(key, Counter())[txn.merchant_id] += 1
    samples = _payee_key_samples(rows)

    await queries.delete_merchant_aliases(db, owner_user_id=owner_user_id)
    wanted = {
        key: (tally.most_common(1)[0][0], samples.get(key, key), len(tally) > 1)
        for key, tally in merchants_by_key.items()
    }
    flagged = await _write_payee_aliases(db, wanted, owner_user_id=owner_user_id)
    return {"transactions": len(rows), "keys": len(wanted), "ambiguous": flagged}
