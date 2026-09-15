"""The id a table prints is the id ``llm use`` takes.

The catalog stores what each provider calls a model, and several repeat the
vendor in it: ``gemini/gemini-3`` beside a Vendor column that already says
"gemini". Dropping the prefix for display is only safe if the printed form
still resolves, so the two halves are tested together.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.llm import queries
from app.services.ai.domains.llm.catalog import LLMListResult
from app.services.ai.models.llm.large_language_model import LargeLanguageModel
from app.services.ai.models.llm.llm_org import LLMOrg


class TestWhatTheTableShows:
    def _row(self, model_id: str, vendor: str) -> LLMListResult:
        return LLMListResult(
            model_id=model_id,
            title=model_id,
            vendor=vendor,
            family=None,
            color="#000",
            context_window=1,
            input_price=None,
            output_price=None,
            released_on=None,
        )

    def test_a_repeated_vendor_prefix_is_dropped(self) -> None:
        assert self._row("gemini/gemini-3", "gemini").display_id == "gemini-3"

    def test_case_does_not_matter(self) -> None:
        assert self._row("OpenAI/gpt-4o", "openai").display_id == "gpt-4o"

    def test_an_unrelated_prefix_is_kept(self) -> None:
        """``meta/llama-3`` served by Bedrock is not a repeat."""
        assert self._row("meta/llama-3", "bedrock").display_id == "meta/llama-3"

    def test_an_id_without_a_prefix_is_untouched(self) -> None:
        assert self._row("claude-opus-4", "anthropic").display_id == "claude-opus-4"


class TestWhatTheLookupAccepts:
    async def _catalog(self, session: AsyncSession, *ids: str) -> None:
        org = LLMOrg(slug="gemini", name="gemini", color="#000", icon_path="")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        for model_id in ids:
            session.add(
                LargeLanguageModel(
                    model_id=model_id,
                    title=model_id,
                    served_by_org_id=org.id,
                )
            )
        await session.commit()

    @pytest.mark.asyncio
    async def test_the_stored_id_resolves(self, async_db_session: AsyncSession) -> None:
        await self._catalog(async_db_session, "gemini/gemini-3")

        found = await queries.llm_with_vendor(async_db_session, "gemini/gemini-3")

        assert found is not None

    @pytest.mark.asyncio
    async def test_the_displayed_id_resolves_too(
        self, async_db_session: AsyncSession
    ) -> None:
        """Otherwise the table prints something that cannot be pasted back."""
        await self._catalog(async_db_session, "gemini/gemini-3")

        found = await queries.llm_with_vendor(async_db_session, "gemini-3")

        assert found is not None
        assert found.model_id == "gemini/gemini-3"

    @pytest.mark.asyncio
    async def test_an_ambiguous_short_id_resolves_to_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        """Two vendors serving one name is not something to guess between."""
        await self._catalog(async_db_session, "a/gpt-4o", "b/gpt-4o")

        assert await queries.llm_with_vendor(async_db_session, "gpt-4o") is None
