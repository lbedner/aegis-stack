"""The catalog tool: the models this install could use, as typed rows."""

from typing import Any

import pytest

from app.services.ai.domains.llm import catalog
from app.services.ai.domains.llm.catalog import CatalogAnswer, LLMListResult


def _row(model_id: str) -> LLMListResult:
    return LLMListResult(
        model_id=model_id,
        title=model_id.upper(),
        vendor="openai",
        family=None,
        color="#10A37F",
        context_window=128_000,
        input_price=2.5,
        output_price=10.0,
        released_on="2026-01-01",
        lab="OpenAI",
        lab_icon_b64="iVBORw0KGgo",
    )


@pytest.mark.asyncio
async def test_the_catalog_answers_in_its_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog left her prompt for this tool (2026-10-16): each row is
    one she can read (no logo bytes or colours), and the answer says when
    it was read."""
    asked: dict[str, Any] = {}

    async def listed(**filters: Any) -> list[LLMListResult]:
        asked.update(filters)
        return [_row("gpt-x")]

    monkeypatch.setattr(catalog, "list_models", listed)

    found = await catalog.catalog(text="gpt", vendor="openai", modality="vision")

    answer = CatalogAnswer.model_validate(found)
    assert [m.model_id for m in answer.models] == ["gpt-x"]
    assert (asked["pattern"], asked["vendor"], asked["modality"]) == (
        "gpt",
        "openai",
        "vision",
    )
