"""Which hats an organization wears: maker, server, or both."""

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

if TYPE_CHECKING:
    from .llm_org import LLMOrg

# The two things an org can be to a model. Kept as data rather than two
# booleans so a third role (a hosting partner, a fine-tuner) is a row,
# not a schema change.
ROLE_MAKER = "maker"
ROLE_SERVER = "server"
ORG_ROLES = (ROLE_MAKER, ROLE_SERVER)


class LLMOrgRole(SQLModel, table=True):
    """One role an org plays. An org that both builds and serves has
    two rows, which is the whole reason this is a link table."""

    __tablename__ = "llm_org_role"
    __table_args__ = (UniqueConstraint("org_id", "role", name="uq_llm_org_role"),)

    id: int | None = Field(default=None, primary_key=True)
    org_id: int = Field(foreign_key="llm_org.id", index=True)
    role: str = Field(max_length=16)

    org: "LLMOrg" = Relationship(back_populates="roles")

    def __repr__(self) -> str:
        return f"<LLMOrgRole org_id={self.org_id} role={self.role}>"
