"""
LLM sync service for updating the model catalog from public APIs.

Fetches model data from OpenRouter and LiteLLM, merges them,
and upserts to the database.
"""

from sqlmodel import Session

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
    CATALOG_MODES,
    MergedLLMData,
    is_cloud_syncable,
    merge_model_data,
)
from app.services.ai.domains.llm.etl.provider_marks import attach_provider_marks
from app.services.ai.domains.llm.etl.queries import (  # noqa: F401
    CatalogStats,
    catalog_is_populated,
    get_catalog_stats,
    local_models_present,
)
from app.services.ai.domains.llm.etl.results import SyncResult
from app.services.ai.domains.llm.etl.speech_sync import sync_speech
from app.services.ai.domains.llm.etl.upserts import UpsertMixin
from app.services.ai.domains.llm.etl.vendor_metadata import (
    VENDOR_METADATA as VENDOR_METADATA,
)
from app.services.ai.domains.llm.queries import invalidate_price_cache
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
    from app.components.inference import get_inference_engine
    from app.components.inference.engine import InferenceModel
except (ModuleNotFoundError, ImportError):
    # Inference component not generated, or a missing dependency — either way, gracefully degrade
    get_inference_engine = None  # type: ignore[assignment]
    InferenceModel = None  # type: ignore[assignment, misc]


def sync_source(source: str) -> str:
    """``source`` as the sync reads it: "local" is the inference engine,
    and "ollama", its name from before llama.cpp, is still taken."""
    return "local" if source == "ollama" else source


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
            mode_filter: One mode ("chat", "realtime", ...), "all", or None
                for the kinds the app uses (CATALOG_MODES).
            source: Data source - "cloud" (OpenRouter/LiteLLM), "local" (the
                inference engine), or "all".
            dry_run: If True, don't commit changes to database.

        Returns:
            SyncResult with counts and any errors.
        """
        source = sync_source(source)

        if source == "local":  # what this machine serves only
            result = await self.sync_local(dry_run=dry_run)
        elif source == "all":  # both cloud and this machine, merged
            result = await self._sync_cloud(mode_filter, dry_run)
            result.merge(await self.sync_local(dry_run=dry_run))
        else:
            result = await self._sync_cloud(mode_filter, dry_run)
        if source in ("local", "all"):  # the speech server beside the engine
            result.merge(await sync_speech(self, dry_run))
        if not dry_run:
            # Once per sync, whichever ran: a local-only install never runs
            # the cloud half, and its engine's logo is filled here too.
            await attach_provider_marks(self.session)
        return result

    async def _sync_cloud(
        self,
        mode_filter: str | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Sync LLM catalog from cloud APIs (OpenRouter/LiteLLM).

        Args:
            mode_filter: One mode, "all", or None (CATALOG_MODES).
            dry_run: If True, don't commit changes to database.

        Returns:
            SyncResult with counts and any errors.
        """
        result = SyncResult()
        # None keeps the kinds the app uses (chat and the voice kinds);
        # "all" keeps everything the source lists.
        modes = (mode_filter,) if mode_filter else CATALOG_MODES

        logger.info(f"Starting LLM catalog sync (modes={modes}, dry_run={dry_run})")

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
            merged = [m for m in merged if m.mode in modes]
            logger.info(f"Filtered to {len(merged)} models with modes={modes}")

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
            # Prices are memoized in the shared cache for the recording
            # path; a sync is the only thing that changes them.
            await invalidate_price_cache()

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
        # By slug: it is what the sync looks up and what is unique. A maker
        # lookup names a row for display ("OpenAI") under the same slug.
        self._vendor_cache = {v.slug: v for v in vendors}

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

    async def sync_local(self, dry_run: bool = False) -> SyncResult:
        """Sync the models the app's inference engine serves to the catalog
        (Ollama's, or llama.cpp's one), under the engine's name, each at the
        context it serves while loaded (unknown, 0, while it is not).

        Args:
            dry_run: If True, don't commit changes to database.

        Returns:
            SyncResult with counts and any errors.
        """
        result = SyncResult()

        if get_inference_engine is None:
            result.errors.append("Local inference integration not available")
            return result

        client = get_inference_engine()
        logger.info(f"Syncing models from {client.LABEL} at {client.base_url}")

        status = await client.get_server_status()
        if not status.available:
            error_msg = (
                f"Cannot read models from {client.LABEL} at {client.base_url}. "
                f"Make sure {client.LABEL} is running."
            )
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result
        models = status.installed_models
        served = {m.name: m.context_length for m in status.running_models}

        if not models:
            logger.info(f"No models found in {client.LABEL}")
            return result

        # Pre-load caches
        self._load_caches()

        vendor = self._upsert_vendor(client.NAME, result, dry_run)
        if not vendor:
            return result

        for model in models:
            try:
                self._sync_local_model(
                    model, vendor, served.get(model.name, 0), result, dry_run
                )
            except Exception as e:
                error_msg = f"Failed to sync {client.LABEL} model {model.name}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
                continue
        self._retire_unserved(vendor, {m.model_id for m in models}, result, dry_run)

        if not dry_run:
            self.session.commit()
            await invalidate_price_cache()
            await attach_labs(self.session, [m.model_id for m in models])

        logger.info(
            f"{client.LABEL} sync complete: {result.models_added} models added, "
            f"{result.models_updated} updated, {len(result.errors)} errors"
        )

        return result

    def _retire_unserved(
        self, vendor: LLMOrg, served: set[str], result: SyncResult, dry_run: bool
    ) -> None:
        """Turn off the engine's models it no longer serves (removed, or one
        it cannot load), so the picker stops offering them; serving one
        again turns it back on (``_sync_local_model``)."""
        for model in self._model_cache.values():
            if (
                model.served_by_org_id == vendor.id
                and model.model_id not in served
                and model.enabled
            ):
                model.enabled = False
                if not dry_run:
                    self.session.add(model)
                result.models_updated += 1

    def _sync_local_model(
        self,
        local_model: InferenceModel,
        vendor: LLMOrg,
        context_window: int,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """Sync one model the engine serves to the database.

        Args:
            local_model: The model, as the engine reports it.
            vendor: The engine's vendor record.
            context_window: The context it serves, 0 when not loaded.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.
        """
        model_data = local_model

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
                    self._update_if_changed(existing, "enabled", True),
                    bool(context_window)
                    and self._update_if_changed(
                        existing, "context_window", context_window
                    ),
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
                context_window=context_window,
                streamable=True,
                enabled=True,
                color=VENDOR_METADATA.get(vendor.name, {}).get("color", "#FFFFFF"),
                family=model_data.details.family,
                served_by_org_id=vendor.id,
            )

            if not dry_run:
                self.session.add(model)
                self.session.flush()

            self._model_cache[model_id] = model
            result.models_added += 1
            logger.debug(f"Added local model: {model_id}")


async def sync_llm_catalog(
    session: Session,
    mode: str | None = None,
    source: str = "cloud",
    dry_run: bool = False,
) -> SyncResult:
    """Sync LLM catalog from public APIs or local sources.

    Convenience function for one-off syncs.

    Args:
        session: Database session.
        mode: One mode ("chat", "realtime", ...), "all", or None for the
            kinds the app uses (chat and the voice kinds).
        source: Data source - "cloud", "local", or "all".
        dry_run: If True, don't commit changes.

    Returns:
        SyncResult with sync statistics.
    """
    service = LLMSyncService(session)
    return await service.sync(mode_filter=mode, source=source, dry_run=dry_run)
