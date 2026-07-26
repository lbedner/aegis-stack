"""Runtime active-model selection.

One row, holding the model the app is currently using. Written by the Cloud
Catalog tab and by ``llm use``; read at startup and applied to the live
settings, so switching models takes effect without a restart and without
rewriting ``.env``.

``.env`` still supplies the bootstrap default (``AI_MODEL`` / ``AI_PROVIDER``)
for a fresh install and for stacks with no catalog database.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class LLMActiveSelection(SQLModel, table=True):
    """The active model, at most one row per owner.

    ``owner_user_id`` is NULL for the install-wide default, which is the only
    value a stack without the auth service ever writes. The column is carried
    from the start so per-user selection is later a resolution change rather
    than a migration on a shipped table; the FK to ``user`` is added
    separately when auth is present, mirroring how finance links its
    owner-scoped tables.
    """

    __tablename__ = "llm_active_selection"

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None, index=True)
    model_id: str = Field(index=True)
    provider: str | None = Field(default=None)
    updated_at: datetime = Field(default_factory=_utcnow)
