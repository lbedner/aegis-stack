"""OFX / QFX (Quicken) statement parser — dedup LANE 1 via FITID.

Handles both OFX 1.x SGML (Chase/AMEX/Fidelity QFX downloads) and 2.x XML via
``ofxtools``, which auto-detects the flavor. OFX amounts are already
outflow-negative, so we trust the sign on ``TRNAMT``, not the ``TRNTYPE`` label.
``ofxtools`` is imported lazily so this module loads even in a
finance-without-import build.
"""

from __future__ import annotations

import io

from app.services.finance.adapters.importers.base import ParsedTransaction
from app.services.finance.utils import to_cents


def parse_ofx(data: bytes, *, source: str = "ofx") -> list[ParsedTransaction]:
    """Parse OFX/QFX bytes into source-agnostic ``ParsedTransaction`` records.

    ``source`` is stored on each transaction (``"qfx"`` for Quicken downloads,
    ``"ofx"`` otherwise) and is part of the LANE-1 dedup key.
    """
    from ofxtools.Parser import OFXTree

    tree = OFXTree()
    tree.parse(io.BytesIO(data))
    ofx = tree.convert()

    parsed: list[ParsedTransaction] = []
    for statement in ofx.statements:
        account = getattr(statement, "account", None)
        account_key = getattr(account, "acctid", None) if account is not None else None
        for txn in statement.transactions:
            cents = to_cents(txn.trnamt)
            fitid = getattr(txn, "fitid", None)
            check_number = getattr(txn, "checknum", None)
            payee = txn.name or getattr(txn, "payee", None)
            parsed.append(
                ParsedTransaction(
                    date=txn.dtposted.date(),
                    amount=cents,
                    source=source,
                    external_id=str(fitid) if fitid is not None else None,
                    external_id_source="fitid",
                    raw_amount=cents,
                    raw_sign_convention="ofx_signed",
                    name=payee,
                    original_description=payee,
                    memo=getattr(txn, "memo", None),
                    check_number=str(check_number) if check_number else None,
                    account_key=str(account_key) if account_key else None,
                )
            )
    return parsed
