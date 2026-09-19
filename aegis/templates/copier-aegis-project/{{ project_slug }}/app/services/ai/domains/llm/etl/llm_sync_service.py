"""
LLM sync service for updating the model catalog from public APIs.

Fetches model data from OpenRouter and LiteLLM, merges them,
and upserts to the database.
"""

from sqlmodel import Session

from app.core.config import settings
from app.core.log import logger

# Re-exported: callers have always reached the catalog readers through
# this module, and moving them out did not move their address.
from app.services.ai.domains.llm.etl import queries
from app.services.ai.domains.llm.etl.clients.litellm_client import LiteLLMClient
from app.services.ai.domains.llm.etl.clients.openrouter_client import (
    OpenRouterClient,
    OpenRouterModelIndex,
)
from app.services.ai.domains.llm.etl.lab_resolver import attach_labs
from app.services.ai.domains.llm.etl.mappers.llm_mapper import (
    MergedLLMData,
    is_cloud_syncable,
    merge_model_data,
)
from app.services.ai.domains.llm.etl.queries import (  # noqa: F401
    CatalogStats,
    catalog_is_populated,
    get_catalog_stats,
    ollama_models_present,
)
from app.services.ai.domains.llm.etl.results import SyncResult
from app.services.ai.domains.llm.etl.upserts import UpsertMixin
from app.services.ai.domains.llm.etl.vendor_metadata import (
    VENDOR_METADATA as VENDOR_METADATA,
)
from app.services.ai.models.llm import (
    Direction,
    LargeLanguageModel,
    LLMDeployment,
    LLMModality,
    LLMOrg,
    LLMPrice,
    Modality,
)

try:
    from app.services.ai.domains.llm.ollama import OllamaClient, OllamaModel
except (ModuleNotFoundError, ImportError):
    # Ollama module not generated or empty (ollama_mode is "none"),
    # or missing dependency — either way, gracefully degrade
    OllamaClient = None  # type: ignore[assignment, misc]
    OllamaModel = None  # type: ignore[assignment, misc]


class LLMSyncService(UpsertMixin):
    """Service for syncing LLM catalog from public APIs."""

    def __init__(self, session: Session) -> None:
        """Initialize the sync service.

        Args:
            session: Database session for persistence.
        """
        self.session = session
        self.openrouter_client = OpenRouterClient()
        self.litellm_client = LiteLLMClient()
        self._vendor_cache: dict[str, LLMOrg] = {}
        self._model_cache: dict[str, LargeLanguageModel] = {}
        # Keyed by (llm_id, org_id); ids are None only before the
        # owning row's first flush, and every cache write happens after it.
        self._deployment_cache: dict[tuple[int | None, int | None], LLMDeployment] = {}
        self._price_cache: dict[tuple[int | None, int | None], LLMPrice] = {}
        self._modality_cache: dict[
            int | None, dict[tuple[Modality, Direction], LLMModality]
        ] = {}

    async def sync(
        self,
        mode_filter: str | None = None,
        source: str = "cloud",
        dry_run: bool = False,
    ) -> SyncResult:
        """Sync LLM catalog from public APIs or local sources.

        Args:
            mode_filter: Filter by mode ("chat", "embedding", "all", None).
                        None defaults to "chat".
            source: Data source - "cloud" (OpenRouter/LiteLLM), "ollama", or "all".
            dry_run: If True, don't commit changes to database.

        Returns:
            SyncResult with counts and any errors.
        """
        # Handle Ollama-only sync
        if source == "ollama":
            return await self.sync_ollama(dry_run=dry_run)

        # Handle "all" - sync both cloud and ollama
        if source == "all":
            cloud_result = await self._sync_cloud(mode_filter, dry_run)
            ollama_result = await self.sync_ollama(dry_run=dry_run)
            # Merge results
            cloud_result.vendors_added += ollama_result.vendors_added
            cloud_result.models_added += ollama_result.models_added
            cloud_result.models_updated += ollama_result.models_updated
            cloud_result.errors.extend(ollama_result.errors)
            return cloud_result

        # Default: cloud-only sync
        return await self._sync_cloud(mode_filter, dry_run)

    async def _sync_cloud(
        self,
        mode_filter: str | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Sync LLM catalog from cloud APIs (OpenRouter/LiteLLM).

        Args:
            mode_filter: Filter by mode ("chat", "embedding", "all", None).
            dry_run: If True, don't commit changes to database.

        Returns:
            SyncResult with counts and any errors.
        """
        result = SyncResult()
        mode_filter = mode_filter or "chat"

        logger.info(
            f"Starting LLM catalog sync (mode={mode_filter}, dry_run={dry_run})"
        )

        # Fetch from both sources
        try:
            litellm_models = await self.litellm_client.fetch_models()
        except Exception as e:
            error_msg = f"Failed to fetch from LiteLLM: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result

        try:
            openrouter_models = await self.openrouter_client.fetch_models()
            openrouter_index = OpenRouterModelIndex.from_models(openrouter_models)
        except Exception as e:
            logger.warning(f"Failed to fetch from OpenRouter, continuing without: {e}")
            openrouter_index = OpenRouterModelIndex()

        # Merge data
        merged = merge_model_data(litellm_models, openrouter_index)

        # Filter by mode
        if mode_filter != "all":
            merged = [m for m in merged if m.mode == mode_filter]
            logger.info(f"Filtered to {len(merged)} models with mode={mode_filter}")

        # Local-runner rows are the local sync's business, not the cloud
        # catalog's - see is_cloud_syncable.
        before = len(merged)
        merged = [m for m in merged if is_cloud_syncable(m.model_id)]
        if len(merged) != before:
            logger.info(
                f"Skipped {before - len(merged)} local-runner rows from the "
                "cloud catalog"
            )

        # Pre-load caches
        self._load_caches()

        # Process each model
        for model_data in merged:
            try:
                self._sync_model(model_data, result, dry_run)
            except Exception as e:
                error_msg = f"Failed to sync {model_data.model_id}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
                continue

        if not dry_run:
            self.session.commit()

        logger.info(
            f"Sync complete: {result.vendors_added} vendors added, "
            f"{result.models_added} models added, {result.models_updated} updated, "
            f"{len(result.errors)} errors"
        )

        return result

    def _load_caches(self) -> None:
        """Load the whole catalog into caches, one query per table.

        Everything the per-model loop needs must be here: with ~3,000
        models a single stray per-model lookup is 3,000 queries per run
        (observed live before deployments/prices/modalities were cached).
        """
        vendors = queries.all_rows(self.session, LLMOrg)
        self._vendor_cache = {v.name: v for v in vendors}

        models = queries.all_rows(self.session, LargeLanguageModel)
        self._model_cache = {m.model_id: m for m in models}

        deployments = queries.all_rows(self.session, LLMDeployment)
        self._deployment_cache = {(d.llm_id, d.org_id): d for d in deployments}

        prices = queries.all_rows(self.session, LLMPrice)
        self._price_cache = {(p.llm_id, p.org_id): p for p in prices}

        modalities = queries.all_rows(self.session, LLMModality)
        self._modality_cache = {}
        for record in modalities:
            per_model = self._modality_cache.setdefault(record.llm_id, {})
            per_model[(record.modality, record.direction)] = record

    def _sync_model(
        self,
        data: MergedLLMData,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """Sync a single model to the database.

        Args:
            data: Merged model data.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.
        """
        # Ensure vendor exists
        vendor = self._upsert_vendor(data.vendor, result, dry_run)
        if not vendor:
            return

        # Upsert model
        model = self._upsert_model(data, vendor, result, dry_run)
        if not model:
            return

        # Sync related records
        self._upsert_deployment(model, vendor, data, result, dry_run)
        self._upsert_price(model, vendor, data, result, dry_run)
        self._sync_modalities(model, data, result, dry_run)

    async def sync_ollama(self, dry_run: bool = False) -> SyncResult:
        """Sync locally installed Ollama models to catalog.

        Fetches models from local Ollama server and adds them to the catalog.

        Args:
            dry_run: If True, don't commit changes to database.

        Returns:
            SyncResult with counts and any errors.
        """
        result = SyncResult()

        if OllamaClient is None:
            result.errors.append("Ollama integration not available")
            return result

        # Get Ollama base URL from settings (uses effective URL for Docker/local auto-detection)
        base_url = settings.ollama_base_url_effective
        client = OllamaClient(base_url=base_url)

        # Check if Ollama is available
        if not await client.is_available():
            error_msg = (
                f"Cannot connect to Ollama at {base_url}. "
                "Make sure Ollama is running: ollama serve"
            )
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result

        logger.info(f"Syncing models from Ollama at {base_url}")

        try:
            ollama_models = await client.fetch_models()
        except Exception as e:
            error_msg = f"Failed to fetch models from Ollama: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result

        if not ollama_models:
            logger.info("No models found in Ollama")
            return result

        # Pre-load caches
        self._load_caches()

        # Ensure Ollama vendor exists
        vendor = self._upsert_vendor("ollama", result, dry_run)
        if not vendor:
            return result

        # Process each Ollama model
        for ollama_model in ollama_models:
            try:
                self._sync_ollama_model(ollama_model, vendor, result, dry_run)
            except Exception as e:
                error_msg = f"Failed to sync Ollama model {ollama_model.name}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
                continue

        if not dry_run:
            self.session.commit()
            await attach_labs(self.session, [m.model_id for m in ollama_models])

        logger.info(
            f"Ollama sync complete: {result.models_added} models added, "
            f"{result.models_updated} updated, {len(result.errors)} errors"
        )

        return result

    def _sync_ollama_model(
        self,
        ollama_model: OllamaModel,
        vendor: LLMOrg,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """Sync a single Ollama model to the database.

        Args:
            ollama_model: Ollama model data from API.
            vendor: Ollama vendor record.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.
        """
        model_data = ollama_model

        model_id = model_data.model_id  # e.g., "llama3.2" without tag
        existing = self._model_cache.get(model_id)

        # Generate title from model name
        title = model_id.replace("-", " ").replace("_", " ").title()

        # Build description from available metadata (nested in details)
        desc_parts = []
        if model_data.details.family:
            desc_parts.append(f"Family: {model_data.details.family}")
        if model_data.details.parameter_size:
            desc_parts.append(f"Parameters: {model_data.details.parameter_size}")
        if model_data.details.quantization_level:
            desc_parts.append(f"Quantization: {model_data.details.quantization_level}")
        desc_parts.append(f"Size: {model_data.size_gb:.1f} GB")
        description = " | ".join(desc_parts)

        if existing:
            # Update existing model
            changed = any(
                [
                    self._update_if_changed(existing, "title", title),
                    self._update_if_changed(existing, "description", description),
                    self._update_if_changed(existing, "served_by_org_id", vendor.id),
                ]
            )

            if changed:
                if not dry_run:
                    self.session.add(existing)
                result.models_updated += 1
        else:
            # Create new model
            model = LargeLanguageModel(
                model_id=model_id,
                title=title,
                description=description,
                context_window=0,  # Unknown for local models
                streamable=True,
                enabled=True,
                color=VENDOR_METADATA.get("ollama", {}).get("color", "#FFFFFF"),
                family=model_data.details.family,
                served_by_org_id=vendor.id,
            )

            if not dry_run:
                self.session.add(model)
                self.session.flush()

            self._model_cache[model_id] = model
            result.models_added += 1
            logger.debug(f"Added Ollama model: {model_id}")


async def sync_llm_catalog(
    session: Session,
    mode: str = "chat",
    source: str = "cloud",
    dry_run: bool = False,
) -> SyncResult:
    """Sync LLM catalog from public APIs or local sources.

    Convenience function for one-off syncs.

    Args:
        session: Database session.
        mode: Mode filter ("chat", "embedding", "all").
        source: Data source - "cloud", "ollama", or "all".
        dry_run: If True, don't commit changes.

    Returns:
        SyncResult with sync statistics.
    """
    service = LLMSyncService(session)
    return await service.sync(mode_filter=mode, source=source, dry_run=dry_run)
