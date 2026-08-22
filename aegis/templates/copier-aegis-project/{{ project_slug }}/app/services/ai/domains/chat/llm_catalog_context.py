"""
LLM catalog context for AI prompt injection.

Provides Illiana with awareness of available LLM models, their pricing,
and capabilities for informed model selection discussions.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.ai.models.llm import (
    Direction,
    LargeLanguageModel,
    LLMVendor,
    Modality,
)
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

# Pattern to extract YYYYMMDD dates from model IDs (e.g., claude-3-5-sonnet-20241022)
_DATE_PATTERN = re.compile(r"(\d{8})(?:\D|$)")

# Suffixes that indicate alias/pointer models (not the actual versioned model)
_ALIAS_SUFFIXES = ("-latest", ":latest")


def _is_alias_model(model_id: str) -> bool:
    """
    Check if a model_id is an alias pointing to another model.

    Alias models include:
    - Models ending in -latest or :latest (e.g., claude-3-5-sonnet-latest)
    - Short names without dates that duplicate dated versions

    Args:
        model_id: The model identifier string.

    Returns:
        True if this appears to be an alias model.
    """
    # Check for -latest suffix
    return any(model_id.endswith(suffix) for suffix in _ALIAS_SUFFIXES)


def _extract_date_from_model_id(model_id: str) -> datetime | None:
    """
    Extract release date from model_id if it contains a YYYYMMDD pattern.

    Examples:
        - claude-3-5-sonnet-20241022 → 2024-10-22
        - gpt-4o-2024-08-06 → None (not YYYYMMDD format)
        - claude-opus-4-5-20241101 → 2024-11-01

    Args:
        model_id: The model identifier string.

    Returns:
        datetime if a valid YYYYMMDD date is found, None otherwise.
    """
    match = _DATE_PATTERN.search(model_id)
    if not match:
        return None

    date_str = match.group(1)
    try:
        return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


# Number of newest models to show per vendor
TOP_MODELS_PER_VENDOR = 3

# Featured vendors to show models from (ordered by importance)
FEATURED_VENDORS: list[str] = [
    "openai",
    "anthropic",
    "google",
    "xai",
    "mistral",
    "groq",
    "deepseek",
    "dashscope",  # Alibaba/Qwen
    "perplexity",
    "cohere",
    "ai21",
    "meta_llama",
    "cerebras",
]


@dataclass
class FlagshipModel:
    """A flagship model from a vendor with key metrics."""

    vendor: str
    model_id: str
    title: str
    input_cost_per_m: float
    output_cost_per_m: float
    context_window: int
    function_calling: bool
    vision: bool
    structured_output: bool


class LLMCatalogContext:
    """
    Context for LLM catalog injection into AI prompts.

    Provides a curated view of top models from key vendors,
    formatted compactly for prompt injection.

    Performance: Uses batch queries with eager loading (~3 queries total)
    instead of per-vendor queries (was 65+ queries).
    """

    def __init__(self, flagships: list[FlagshipModel]) -> None:
        """Initialize with list of flagship models."""
        self.flagships = flagships

    @classmethod
    def build(cls, session: Session) -> "LLMCatalogContext":
        """
        Build catalog context from database using efficient batch queries.

        Performance optimization:
        - 1 query: Fetch all featured vendors
        - 1 query: Fetch all models with eager-loaded relationships
        - Processing in memory: Group by vendor, take top N

        Args:
            session: Database session for queries.

        Returns:
            LLMCatalogContext with top models from each vendor.
        """
        # Query 1: Get all featured vendors in one query
        vendors = session.exec(
            select(LLMVendor).where(LLMVendor.name.in_(FEATURED_VENDORS))
        ).all()

        if not vendors:
            return cls([])

        # Build vendor lookup maps
        vendor_id_to_name = {v.id: v.name for v in vendors}
        vendor_ids = list(vendor_id_to_name.keys())

        # Query 2: Get all models for featured vendors with eager loading
        # This fetches models + prices + deployments + modalities in ~3 queries
        stmt = (
            select(LargeLanguageModel)
            .where(LargeLanguageModel.llm_vendor_id.in_(vendor_ids))
            .options(
                selectinload(LargeLanguageModel.llm_prices),
                selectinload(LargeLanguageModel.deployments),
                selectinload(LargeLanguageModel.modalities),
            )
        )
        all_models = session.exec(stmt).all()

        # Group models by vendor, filtering out aliases (-latest, etc.)
        vendor_models: dict[int, list[LargeLanguageModel]] = defaultdict(list)
        for model in all_models:
            if model.llm_vendor_id is not None and not _is_alias_model(model.model_id):
                vendor_models[model.llm_vendor_id].append(model)

        # Sort each vendor's models by effective release date (newest first)
        # Uses released_on if available, else extracts date from model_id
        def get_sort_key(m: LargeLanguageModel) -> tuple[bool, float, str]:
            effective_date = m.released_on or _extract_date_from_model_id(m.model_id)
            return (
                effective_date is None,  # False (has date) sorts before True
                -(effective_date.timestamp() if effective_date else 0),
                m.title or m.model_id,
            )

        for vendor_id in vendor_models:
            vendor_models[vendor_id].sort(key=get_sort_key)

        # Build flagship list in vendor priority order, taking top N per vendor
        flagships: list[FlagshipModel] = []
        for vendor_name in FEATURED_VENDORS:
            # Find vendor ID for this name
            vendor_id = next(
                (vid for vid, name in vendor_id_to_name.items() if name == vendor_name),
                None,
            )
            if vendor_id is None:
                continue

            # Take top N models for this vendor
            top_models = vendor_models.get(vendor_id, [])[:TOP_MODELS_PER_VENDOR]
            for model in top_models:
                flagship = cls._model_to_flagship(vendor_name, model)
                flagships.append(flagship)

        return cls(flagships)

    @classmethod
    def _model_to_flagship(
        cls, vendor_name: str, model: LargeLanguageModel
    ) -> FlagshipModel:
        """
        Convert a LargeLanguageModel with loaded relationships to FlagshipModel.

        Args:
            vendor_name: Vendor name string.
            model: Model with eager-loaded prices, deployments, modalities.

        Returns:
            FlagshipModel dataclass.
        """
        # Get first price (models typically have one active price)
        price = model.llm_prices[0] if model.llm_prices else None

        # Get first deployment (models typically have one deployment config)
        deployment = model.deployments[0] if model.deployments else None

        # Check for vision capability in modalities
        has_vision = any(
            m.modality == Modality.IMAGE and m.direction == Direction.INPUT
            for m in model.modalities
        )

        return FlagshipModel(
            vendor=vendor_name,
            model_id=model.model_id,
            title=model.title or model.model_id,
            input_cost_per_m=(
                (price.input_cost_per_token * 1_000_000) if price else 0.0
            ),
            output_cost_per_m=(
                (price.output_cost_per_token * 1_000_000) if price else 0.0
            ),
            context_window=model.context_window or 0,
            function_calling=(deployment.function_calling if deployment else False),
            vision=has_vision,
            structured_output=(deployment.structured_output if deployment else False),
        )

    def format_for_prompt(self) -> str:
        """
        Format catalog data for prompt injection.

        Returns:
            Compact markdown string showing top models grouped by vendor.
        """
        if not self.flagships:
            return ""

        lines = ["LLM Catalog (Top Models by Vendor):"]
        current_vendor = ""

        for m in self.flagships:
            # Add vendor header when vendor changes
            if m.vendor != current_vendor:
                current_vendor = m.vendor
                lines.append(f"\n  {m.vendor.title()}:")

            # Build capabilities list
            caps: list[str] = []
            if m.function_calling:
                caps.append("functions")
            if m.vision:
                caps.append("vision")
            if m.structured_output:
                caps.append("structured")
            caps_str = ", ".join(caps) if caps else "basic"

            # Format context window
            if m.context_window >= 1_000_000:
                ctx_str = f"{m.context_window // 1_000_000}M"
            elif m.context_window >= 1000:
                ctx_str = f"{m.context_window // 1000}K"
            else:
                ctx_str = str(m.context_window)

            # Format line (indented under vendor)
            lines.append(
                f"    - {m.title} | "
                f"${m.input_cost_per_m:.2f}/${m.output_cost_per_m:.2f}/M | "
                f"{ctx_str} ctx | {caps_str}"
            )

        return "\n".join(lines)


def get_llm_catalog_context(session: Session) -> str:
    """
    Get formatted LLM catalog context for prompt injection.

    Convenience function for building and formatting catalog context.

    Args:
        session: Database session.

    Returns:
        Formatted string for prompt injection, or empty string if no data.
    """
    context = LLMCatalogContext.build(session)
    return context.format_for_prompt()


__all__ = ["FlagshipModel", "LLMCatalogContext", "get_llm_catalog_context"]
