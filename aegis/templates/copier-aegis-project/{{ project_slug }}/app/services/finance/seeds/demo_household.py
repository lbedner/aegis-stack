"""The demo household, as data.

Split out of ``demo_seed`` so the numbers that decide what a fresh
install looks like can be read and tuned without scrolling past the
planner and the writers. Everything here is a table; nothing here
touches a database.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DemoAccountSpec(BaseModel):
    """One seeded account. ``key`` is the ledger's stable handle for it."""

    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    account_type: str
    classification: str
    opening_balance: int = 0


DEMO_ACCOUNTS: tuple[DemoAccountSpec, ...] = (
    DemoAccountSpec(
        key="checking",
        name="Chase Total Checking",
        account_type="checking",
        classification="asset",
        # Roughly one paycheck of cushion. A fat checking balance is the
        # single thing that makes this dataset undemonstrable: nothing
        # dips it, so the projection, the cash-runway rule and the
        # minimum-payment rule all have nothing to point at.
        opening_balance=190_000,
    ),
    DemoAccountSpec(
        key="savings",
        name="Ally Online Savings",
        account_type="savings",
        classification="asset",
        # Where the monthly surplus goes. Savings growing while checking
        # stays thin is both realistic and the only way net worth trends
        # up without hiding the month-to-month squeeze.
        opening_balance=40_000,
    ),
    DemoAccountSpec(
        key="card",
        name="Amex Blue Cash Preferred",
        account_type="credit_card",
        classification="liability",
    ),
    DemoAccountSpec(
        key="home",
        name="Primary Residence",
        account_type="property",
        classification="asset",
        opening_balance=52_500_000,
    ),
    DemoAccountSpec(
        key="brokerage",
        name="Fidelity Brokerage",
        account_type="brokerage",
        classification="asset",
    ),
    DemoAccountSpec(
        key="mortgage",
        name="Mortgage",
        account_type="loan",
        classification="liability",
        opening_balance=31_842_000,
    ),
)
DEMO_ACCOUNT_NAMES: tuple[str, ...] = tuple(a.name for a in DEMO_ACCOUNTS)

# Positions held in the brokerage account: (ticker, name, unit price in cents).
DEMO_SECURITIES: tuple[tuple[str, str, int], ...] = (
    ("VTI", "Vanguard Total Stock Market ETF", 29_142),
    ("VXUS", "Vanguard Total International Stock ETF", 6_488),
    ("BND", "Vanguard Total Bond Market ETF", 7_326),
)

# Two earners on two rhythms. One salary on one cadence lands every
# paycheck on the same two days of the month, which is neither what a
# household looks like nor enough for cadence detection to be interesting.
_BIWEEKLY_PAY = ("Payroll - Meridian Health", 162_400)
_SEMI_MONTHLY_PAY = ("Payroll - Lakeside Schools", 118_000)

# Monthly fixed bills on the checking account: (day, payee, amount, category).
_FIXED_CHECKING: tuple[tuple[int, str, int, str], ...] = (
    (1, "Mortgage Payment", -218_400, "LOAN_PAYMENTS"),
    (5, "State Farm Auto", -16_840, "GENERAL_SERVICES"),
    (12, "Comcast Xfinity", -8_999, "RENT_AND_UTILITIES"),
    (18, "Verizon Wireless", -14_500, "RENT_AND_UTILITIES"),
    (22, "City Water & Sewer", -6_150, "RENT_AND_UTILITIES"),
)
# Monthly subscriptions on the card: (day, payee, amount, category).
_SUBSCRIPTIONS: tuple[tuple[int, str, int, str], ...] = (
    (3, "Apple iCloud+", -299, "ENTERTAINMENT"),
    (6, "Netflix", -1_549, "ENTERTAINMENT"),
    (9, "Peloton App", -1_299, "PERSONAL_CARE"),
    (11, "Spotify", -1_199, "ENTERTAINMENT"),
    (16, "Blue Ridge Fitness", -4_900, "PERSONAL_CARE"),
)
# The subscription that crept. Detection needs the old price several
# times before the new one, so the rise reads as a change rather than as
# the way it always was: (payee, new amount, months back it changed).
_PRICE_HIKE = ("Netflix", -2_054, 2)

# Everyday card spend: (payee, category, times per month, typical amount,
# jitter). Ordered roughly by how often a household actually swipes, and
# spread across categories so the spending donut has a shape rather than
# two slices and an "Other".
_CARD_MERCHANTS: tuple[tuple[str, str, tuple[int, int], int, float], ...] = (
    ("Starbucks", "FOOD_AND_DRINK", (9, 13), -685, 0.35),
    ("Hudson Valley Grounded", "FOOD_AND_DRINK", (5, 8), -742, 0.30),
    ("Whole Foods Market", "FOOD_AND_DRINK", (3, 5), -7_200, 0.40),
    ("Trader Joe's", "FOOD_AND_DRINK", (3, 4), -5_100, 0.35),
    ("Chipotle", "FOOD_AND_DRINK", (4, 6), -2_240, 0.30),
    ("Panera Bread", "FOOD_AND_DRINK", (3, 5), -1_860, 0.30),
    ("Thai Basil Kitchen", "FOOD_AND_DRINK", (1, 3), -3_400, 0.35),
    ("Corner Deli", "FOOD_AND_DRINK", (3, 6), -1_425, 0.30),
    ("Amazon", "GENERAL_MERCHANDISE", (5, 8), -3_400, 0.60),
    ("Target", "GENERAL_MERCHANDISE", (2, 3), -5_900, 0.45),
    ("Costco Wholesale", "GENERAL_MERCHANDISE", (1, 2), -13_500, 0.35),
    ("Shell", "TRANSPORTATION", (2, 3), -4_600, 0.25),
    ("Chevron", "TRANSPORTATION", (1, 2), -4_200, 0.25),
    ("Uber", "TRANSPORTATION", (4, 7), -1_940, 0.45),
    ("Metro Parking", "TRANSPORTATION", (2, 5), -900, 0.30),
    ("CVS Pharmacy", "MEDICAL", (2, 4), -2_830, 0.50),
    ("Ace Hardware", "HOME_IMPROVEMENT", (1, 2), -4_800, 0.55),
    ("Regal Cinemas", "ENTERTAINMENT", (0, 1), -3_420, 0.20),
)

# One-offs, dated backwards from the anchor: (months back, day, account,
# payee, amount, category). These are the rows that give a surface
# something to say - a finding to raise, a charge worth splitting, a
# month that broke its own pattern.
_ONE_OFFS: tuple[tuple[int, int, str, str, int, str], ...] = (
    (7, 14, "card", "Delta Air Lines", -48_600, "TRAVEL"),
    (5, 9, "card", "Bayside Auto Repair", -124_075, "TRANSPORTATION"),
    # Inside the rules' windows on purpose: fee_charged floors on the
    # lookback setting and large_transaction looks back 35 days, so an
    # anomaly planted three months ago demos nothing.
    (0, 2, "checking", "Overdraft Fee", -3_500, "BANK_FEES"),
    (0, 3, "card", "Riverside Veterinary", -38_940, "MEDICAL"),
)

# The Review tab's work. Rows a bank hands over with no usable name and
# no category - the shape a real import leaves behind - so Uncategorized
# and No payee have something in them. Card-side, because recent checking
# rows travel through the QIF import path and would be normalised there.
_UNCATEGORIZED: tuple[tuple[int, int, str, int], ...] = (
    (0, 1, "PAYPAL *UNKNOWN 88213", -4_250),
    (0, 4, "VENMO *J OKAFOR", -6_000),
    (1, 22, "ZELLE *SENT 0921", -12_000),
)
_NO_PAYEE: tuple[tuple[int, int, str, int, str], ...] = (
    (0, 2, "POS DEBIT 20260902 4417", -1_875, "FOOD_AND_DRINK"),
    (1, 15, "ACH WITHDRAWAL 0915", -2_990, "GENERAL_MERCHANDISE"),
)

# What the household has actually confirmed as its bills. Confirmation
# used to follow the detector's fixed-amount flag, which promoted grocery
# and coffee rhythms into commitments and skipped the one subscription
# whose price changed - exactly the stream a price-hike finding is about.
_COMMITMENT_PAYEES: frozenset[str] = frozenset(
    {payee for _d, payee, _a, _c in _FIXED_CHECKING}
    | {payee for _d, payee, _a, _c in _SUBSCRIPTIONS}
    | {"Pacific Gas & Electric", "Hartford County Property Tax"}
)

# The bill that makes a month hard: big, real, and not monthly, so it is
# invisible in any "average month" view. Quarterly rather than annual
# because detection needs several occurrences to find a cadence, and four
# fit in a year of history - the last one two months back leaves the next
# due just ahead, which is what puts a genuine trough in the projection.
# No monthly bill can: the paychecks arrive too often to let one build.
_QUARTERLY: tuple[tuple[int, int, str, str, int, str], ...] = tuple(
    (
        months_back,
        18,
        "checking",
        "Hartford County Property Tax",
        -155_000,
        "GOVERNMENT_AND_NON_PROFIT",
    )
    for months_back in (11, 8, 5, 2)
)

_GROCERS: tuple[str, ...] = ("Whole Foods Market", "Trader Joe's")
_CARD_INTEREST_NAME = "Interest Charge"
# A steady autopay, not a percentage of a swinging balance. Paying a
# varying share made the same monthly rhythm detect as TWO streams with
# different amounts, and the forecast then charged both.
_CARD_AUTOPAY = 205_000

_TRANSFER_OUT_NAME = "Transfer to Ally Online Savings"
_INVEST_OUT_NAME = "Transfer to Fidelity Brokerage"
_INVEST_IN_NAME = "Contribution from Chase Total Checking"
_TRANSFER_IN_NAME = "Transfer from Chase Total Checking"
_CARD_PAYMENT_OUT_NAME = "Amex Autopay Payment"
_CARD_PAYMENT_IN_NAME = "Payment Received - Thank You"
_PAYROLL_NAME = "Payroll Direct Deposit"
