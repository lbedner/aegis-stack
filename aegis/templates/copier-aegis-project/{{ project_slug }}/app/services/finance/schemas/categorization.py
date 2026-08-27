"""Category, merchant, payee, and tag shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class CategorySuggestion(BaseModel):
    """A payee-precedent category guess for one still-uncategorized
    transaction - a preview, not a write. The caller decides whether to
    apply it (via the ordinary categorize endpoint)."""

    transaction_id: int
    category_id: int
    category_name: str


class CategorySuggestionListResponse(BaseModel):
    items: list[CategorySuggestion]
    skipped: int


class SuggestCategoriesRequest(BaseModel):
    """POST body for /transactions/auto-categorize. Omitted or empty
    ``transaction_ids`` sweeps the full uncategorized backlog, unchanged
    from before this existed; a non-empty list scopes the sweep to a
    caller-chosen subset (e.g. a checkbox selection)."""

    transaction_ids: list[int] | None = None


class PayeeTotal(BaseModel):
    """One payee's outflow over a window (positive magnitude)."""

    payee: str
    amount: int  # cents, positive
    transaction_count: int


class PayeeListResponse(BaseModel):
    items: list[PayeeTotal]
    total: int


class CategoryUsageResponse(BaseModel):
    """A category plus how it is actually used, for the Categories tab."""

    id: int
    name: str  # flattened "Parent:Child" path as the import produced it
    classification: str  # expense | income | transfer
    is_system: bool
    transaction_count: int
    total: int  # signed cents (negative = net outflow)
    last_used: date | None = None


class CategoryListResponse(BaseModel):
    items: list[CategoryUsageResponse]
    total: int


class CategoryOption(BaseModel):
    """id + name only, for a picker - no usage aggregation."""

    id: int
    name: str


class CategoryOptionListResponse(BaseModel):
    items: list[CategoryOption]


class CategoryCreate(BaseModel):
    """A category typed by hand, in the house ``Parent:Child`` shape.

    Resolved through the same get-or-create the importer uses, so a
    spacing or case variant lands on the row that already exists rather
    than beside it - which is the whole reason inline creation was
    withheld from the picker for so long.
    """

    name: str = Field(min_length=1, max_length=128)


class MerchantResponse(BaseModel):
    """A payee: the stable identity behind a raw bank descriptor.

    The usage fields are how the payee directory shows weight rather than
    a bare list of names - which payee is worth correcting depends on how
    much money runs through it. They default to zero so the assign picker,
    which asks for the same list, is unaffected.
    """

    id: int
    name: str
    website_url: str | None = None
    logo_url: str | None = None
    default_category_id: int | None = None
    transaction_count: int = 0
    total_amount: int = 0
    last_date: date | None = None
    # Resolved brand icon, so the directory can SHOW the logo it exists to
    # let you correct. Same base64 inlining the register uses.
    icon_b64: str | None = None


class MerchantListResponse(BaseModel):
    items: list[MerchantResponse]
    total: int


class MerchantCreate(BaseModel):
    name: str
    # Optional real address ("aegis-stack.io") - used for the
    # brand icon instead of guessing <name>.com.
    website_url: str | None = None


class MerchantUpdate(BaseModel):
    """A partial edit of a payee.

    Every field is optional AND nullable, which are different things here:
    omitting ``website_url`` leaves it alone, sending ``""`` clears it.
    The route passes only what the client actually set
    (``exclude_unset``), so a patch that fixes an address cannot blank the
    default category by saying nothing about it.
    """

    name: str | None = None
    website_url: str | None = None
    default_category_id: int | None = None


class MerchantMerge(BaseModel):
    """Fold ``source_ids`` into the payee in the path. Losers are soft
    deleted; their transactions and bills repoint to the survivor."""

    source_ids: list[int]


class TagRef(BaseModel):
    """A tag as it rides a transaction row - identity plus display facts."""

    id: int
    name: str
    color: str | None = None


class TagResponse(TagRef):
    """One row of the tag directory: the tag plus how many transactions
    wear it."""

    transaction_count: int = 0


class TagAssign(BaseModel):
    """Attach one tag (created on first use) to many transactions - the
    bulk-selection verb, same shape as ``MerchantAssign``."""

    transaction_ids: list[int]
    name: str


class MerchantAssign(BaseModel):
    """``merchant_id=None`` clears the payee off the given transactions.

    ``category_id``, when given, also files those transactions under that
    category AND remembers it on the payee (``default_category_id``) - the
    moment you name a payee is the moment you know what it is, and a payee
    that carries its own category is what stops the categorizer guessing
    at the same descriptor forever.
    """

    transaction_ids: list[int]
    merchant_id: int | None = None
    category_id: int | None = None


class MerchantCategorySummary(BaseModel):
    """What categories a payee's transactions currently use - the basis
    for pre-filling the "also set category" offer, and for saying out loud
    when a payee's own history disagrees with itself."""

    merchant_id: int
    default_category_id: int | None = None
    # Most-used category across this payee's transactions (None when it has
    # none categorized yet), plus how lopsided that is.
    dominant_category_id: int | None = None
    dominant_category_name: str | None = None
    dominant_count: int = 0
    total: int = 0
    distinct_categories: int = 0


class PayeeGroup(BaseModel):
    """Payee-less transactions sharing one descriptor key - the unit the
    No-payee queue is actually worked in."""

    key: str
    suggested_name: str
    count: int
    sample: str
    total_amount: int


class PayeeGroupListResponse(BaseModel):
    """``items`` is a page (biggest groups first); the totals describe the
    whole backlog behind it, so the UI can say what the page leaves out."""

    items: list[PayeeGroup]
    total: int  # distinct groups overall, NOT len(items)
    total_transactions: int = 0


class PayeeGroupAssign(BaseModel):
    """Name one or more groups at once. ``merchant_id`` attaches an
    existing payee; ``name`` creates (or reuses) one by name.

    ``keys`` is a LIST because one brand routinely splits across many
    groups - the descriptor carries a store, a city and a transaction id,
    so "DOORDASH*CROWN FRIEDSAN...", "BT*DD *DOORDASH MCDOSAN..." and
    "VENMO *DOORDASH XXX-XXX-4430" land in 48 separate groups for a
    single payee. Naming them one dialog at a time is 48 decisions for
    one fact, so the caller selects the whole set and sends it together.
    """

    keys: list[str]
    merchant_id: int | None = None
    name: str | None = None
    website_url: str | None = None
    category_id: int | None = None


class MerchantMergeResult(BaseModel):
    """Transactions repointed onto the surviving payee, and how many
    source payees were folded in."""

    moved: int
    merged: int


class MerchantAssignResult(BaseModel):
    updated: int


class TagRemoveResult(BaseModel):
    removed: int


class PayeeGroupAssignResult(BaseModel):
    """``merchant_id`` echoes the payee the groups landed on - it may have
    been created by this same call, so the caller cannot know it up front."""

    updated: int
    merchant_id: int
