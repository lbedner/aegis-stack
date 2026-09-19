"""Deterministic demo dataset for the finance service.

Turns an empty install into one that looks like a working app: a
handful of accounts, months of believable activity, detected recurring
streams and transfers, investment positions, and a net-worth curve.

Everything goes through the real service layer rather than raw
inserts, so the seeded data exercises the same code paths a real
import does - and stays correct when those paths change.

Two properties make it safe to re-run. **Marked**: seeded accounts
carry ``metadata["demo_seed"]`` and everything else hangs off them, so
identification never depends on names and clearing cannot touch real
data that happens to share a payee. **Deterministic**: the ledger is
planned by a pure function off a fixed seed, so the same anchor date
always produces the same dataset.

A package rather than one module, split by what each half does:

- ``shared``  the demo marker, and who counts as a demo account
- ``write``   accounts, transactions, valuations, positions
- ``curate``  the passes that make it look worked-on
- ``clear``   removing it again without touching anything real
- ``seed``    one pass: clear, write, curate, count

The household table moved modules; its address did not - the ledger
vocabulary is re-exported here as it always was.
"""

from app.services.finance.seeds.demo_household import (
    DEMO_ACCOUNT_NAMES,
    DEMO_ACCOUNTS,
    DEMO_SECURITIES,
    DemoAccountSpec,
)
from app.services.finance.seeds.demo_plan import (
    PlannedSplit,
    PlannedTransaction,
    build_demo_ledger,
)
from app.services.finance.seeds.demo_seed.clear import (
    clear_demo,
    count_foreign_accounts,
)
from app.services.finance.seeds.demo_seed.seed import seed_demo
from app.services.finance.seeds.demo_seed.shared import DemoSeedResult

__all__ = [
    "DEMO_ACCOUNTS",
    "DEMO_ACCOUNT_NAMES",
    "DEMO_SECURITIES",
    "DemoAccountSpec",
    "DemoSeedResult",
    "PlannedSplit",
    "PlannedTransaction",
    "build_demo_ledger",
    "clear_demo",
    "count_foreign_accounts",
    "seed_demo",
]
