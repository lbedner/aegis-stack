"""
LLM sync service for updating the model catalog from public APIs.

Fetches model data from OpenRouter and LiteLLM, merges them,
and upserts to the database.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.log import logger
from app.services.ai.domains.llm.etl.clients.litellm_client import LiteLLMClient
from app.services.ai.domains.llm.etl.clients.openrouter_client import (
    OpenRouterClient,
    OpenRouterModelIndex,
)
from app.services.ai.domains.llm.etl.lab_resolver import _grant_role, attach_labs
from app.services.ai.domains.llm.etl.mappers.llm_mapper import (
    MergedLLMData,
    is_cloud_syncable,
    merge_model_data,
)
from app.services.ai.domains.llm.etl.vendor_metadata import (
    VENDOR_METADATA as VENDOR_METADATA,
)
from app.services.ai.models.llm import (
    ROLE_SERVER,
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


@dataclass
class SyncResult:
    """Result of an LLM catalog sync operation."""

    vendors_added: int = 0
    vendors_updated: int = 0
    models_added: int = 0
    models_updated: int = 0
    deployments_synced: int = 0
    prices_synced: int = 0
    modalities_synced: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_synced(self) -> int:
        """Total number of records synced."""
        return (
            self.vendors_added
            + self.vendors_updated
            + self.models_added
            + self.models_updated
        )


@dataclass
class CatalogStats:
    """Statistics for the LLM catalog."""

    vendor_count: int
    model_count: int
    deployment_count: int
    price_count: int
    top_vendors: list[tuple[str, int]]


class LLMSyncService:
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
        vendors = self.session.exec(select(LLMOrg)).all()
        self._vendor_cache = {v.name: v for v in vendors}

        models = self.session.exec(select(LargeLanguageModel)).all()
        self._model_cache = {m.model_id: m for m in models}

        deployments = self.session.exec(select(LLMDeployment)).all()
        self._deployment_cache = {(d.llm_id, d.org_id): d for d in deployments}

        prices = self.session.exec(select(LLMPrice)).all()
        self._price_cache = {(p.llm_id, p.org_id): p for p in prices}

        modalities = self.session.exec(select(LLMModality)).all()
        self._modality_cache = {}
        for record in modalities:
            per_model = self._modality_cache.setdefault(record.llm_id, {})
            per_model[(record.modality, record.direction)] = record

    def _update_if_changed(self, obj: Any, field: str, new_value: Any) -> bool:
        """Update field if value changed, return True if changed."""
        if getattr(obj, field) != new_value:
            setattr(obj, field, new_value)
            return True
        return False

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

    def _upsert_vendor(
        self,
        vendor_name: str,
        result: SyncResult,
        dry_run: bool,
    ) -> LLMOrg | None:
        """Upsert a vendor record.

        Args:
            vendor_name: Vendor name.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.

        Returns:
            LLMOrg instance or None on error.
        """
        if vendor_name in self._vendor_cache:
            return self._vendor_cache[vendor_name]

        # Get metadata for known vendors
        metadata = VENDOR_METADATA.get(vendor_name, {})

        vendor = LLMOrg(
            slug=vendor_name,
            name=vendor_name,
            description=metadata.get("description", f"{vendor_name.title()} models"),
            color=metadata.get("color", "#6B7280"),
            api_base=metadata.get("api_base", ""),
            auth_method="api-key",
        )

        if not dry_run:
            self.session.add(vendor)
            self.session.flush()
            # Appearing in the catalog as a model's provider IS the
            # server hat; the maker hat is granted by lab resolution.
            _grant_role(self.session, vendor, ROLE_SERVER)

        self._vendor_cache[vendor_name] = vendor
        result.vendors_added += 1
        logger.debug(f"Added vendor: {vendor_name}")

        return vendor

    def _upsert_model(
        self,
        data: MergedLLMData,
        vendor: LLMOrg,
        result: SyncResult,
        dry_run: bool,
    ) -> LargeLanguageModel | None:
        """Upsert a model record.

        Args:
            data: Merged model data.
            vendor: Parent vendor.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.

        Returns:
            LargeLanguageModel instance or None on error.
        """
        existing = self._model_cache.get(data.model_id)

        if existing:
            changed = any(
                [
                    self._update_if_changed(existing, "title", data.title),
                    self._update_if_changed(existing, "description", data.description),
                    self._update_if_changed(
                        existing, "context_window", data.context_window
                    ),
                    self._update_if_changed(existing, "streamable", data.streamable),
                    self._update_if_changed(existing, "family", data.family),
                    self._update_if_changed(existing, "served_by_org_id", vendor.id),
                    self._update_if_changed(existing, "released_on", data.created_at),
                ]
            )

            if changed:
                if not dry_run:
                    self.session.add(existing)
                result.models_updated += 1

            return existing
        else:
            # Create new model
            model = LargeLanguageModel(
                model_id=data.model_id,
                title=data.title,
                description=data.description,
                context_window=data.context_window,
                streamable=data.streamable,
                enabled=True,
                color=VENDOR_METADATA.get(data.vendor, {}).get("color", "#6B7280"),
                family=data.family,
                served_by_org_id=vendor.id,
                released_on=data.created_at,
            )

            if not dry_run:
                self.session.add(model)
                self.session.flush()

            self._model_cache[data.model_id] = model
            result.models_added += 1
            logger.debug(f"Added model: {data.model_id}")

            return model

    def _upsert_deployment(
        self,
        model: LargeLanguageModel,
        vendor: LLMOrg,
        data: MergedLLMData,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """Upsert a deployment record.

        Args:
            model: Parent model.
            vendor: Deploying vendor.
            data: Merged model data.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.
        """
        existing = self._deployment_cache.get((model.id, vendor.id))

        if existing:
            changed = any(
                [
                    self._update_if_changed(
                        existing, "output_max_tokens", data.max_output_tokens or 4096
                    ),
                    self._update_if_changed(
                        existing, "function_calling", data.supports_function_calling
                    ),
                    self._update_if_changed(
                        existing, "structured_output", data.supports_structured_output
                    ),
                    self._update_if_changed(
                        existing, "input_cache", data.supports_prompt_caching
                    ),
                ]
            )

            if changed:
                if not dry_run:
                    self.session.add(existing)
                result.deployments_synced += 1
        else:
            # Create new deployment
            deployment = LLMDeployment(
                llm_id=model.id,
                org_id=vendor.id,
                speed=50,  # Default - would need benchmarks
                intelligence=50,
                reasoning=50,
                output_max_tokens=data.max_output_tokens or 4096,
                function_calling=data.supports_function_calling,
                structured_output=data.supports_structured_output,
                input_cache=data.supports_prompt_caching,
            )

            if not dry_run:
                self.session.add(deployment)
            if model.id is not None:
                # A dry-run model never flushed, so its id is None - caching
                # under (None, vendor) would alias every new model together.
                self._deployment_cache[(model.id, vendor.id)] = deployment
            result.deployments_synced += 1

    def _upsert_price(
        self,
        model: LargeLanguageModel,
        vendor: LLMOrg,
        data: MergedLLMData,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """Upsert a price record.

        Args:
            model: Parent model.
            vendor: Pricing vendor.
            data: Merged model data.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.
        """
        existing = self._price_cache.get((model.id, vendor.id))

        if existing:
            changed = any(
                [
                    self._update_if_changed(
                        existing, "input_cost_per_token", data.input_cost_per_token
                    ),
                    self._update_if_changed(
                        existing, "output_cost_per_token", data.output_cost_per_token
                    ),
                    self._update_if_changed(
                        existing,
                        "cache_input_cost_per_token",
                        data.cache_read_cost_per_token,
                    ),
                ]
            )

            if changed:
                # Only update effective_date when prices actually change
                existing.effective_date = datetime.now(UTC)
                if not dry_run:
                    self.session.add(existing)
                result.prices_synced += 1
        else:
            # Create new price
            price = LLMPrice(
                llm_id=model.id,
                org_id=vendor.id,
                input_cost_per_token=data.input_cost_per_token,
                output_cost_per_token=data.output_cost_per_token,
                cache_input_cost_per_token=data.cache_read_cost_per_token,
                effective_date=datetime.now(UTC),
            )

            if not dry_run:
                self.session.add(price)
            if model.id is not None:
                self._price_cache[(model.id, vendor.id)] = price
            result.prices_synced += 1

    def _sync_modalities(
        self,
        model: LargeLanguageModel,
        data: MergedLLMData,
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """Sync modality records for a model.

        Args:
            model: Parent model.
            data: Merged model data.
            result: SyncResult to update.
            dry_run: If True, don't persist changes.
        """
        # Build set of new modalities from API data
        new_modalities: set[tuple[Modality, Direction]] = set()
        for mod_str in data.input_modalities:
            try:
                new_modalities.add((Modality(mod_str.lower()), Direction.INPUT))
            except ValueError:
                continue
        for mod_str in data.output_modalities:
            try:
                new_modalities.add((Modality(mod_str.lower()), Direction.OUTPUT))
            except ValueError:
                continue

        if dry_run:
            result.modalities_synced += len(new_modalities)
            return

        existing_modalities = self._modality_cache.setdefault(model.id, {})

        # Find what to add and what to delete
        existing_set = set(existing_modalities.keys())
        to_add = new_modalities - existing_set
        to_delete = existing_set - new_modalities

        # No changes needed
        if not to_add and not to_delete:
            return

        # Delete removed modalities
        for key in to_delete:
            self.session.delete(existing_modalities.pop(key))

        if to_delete:
            self.session.flush()

        # Add new modalities
        for modality, direction in to_add:
            mod_record = LLMModality(
                llm_id=model.id,
                modality=modality,
                direction=direction,
            )
            self.session.add(mod_record)
            existing_modalities[(modality, direction)] = mod_record
            result.modalities_synced += 1

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
        ollama_model: "OllamaModel",
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


def catalog_is_populated(session: Session) -> bool:
    """Whether any model is already in the catalog.

    The webserver startup hook syncs only into an EMPTY catalog; once
    populated, the scheduler's periodic job owns freshness. Before this
    guard every startup (and every dev hot-reload) re-ran a full sync -
    tens of thousands of queries against a catalog that was already
    current.
    """
    first = session.exec(select(LargeLanguageModel.id).limit(1)).first()
    return first is not None


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


def get_catalog_stats(session: Session) -> CatalogStats:
    """Get LLM catalog statistics.

    Args:
        session: Database session.

    Returns:
        CatalogStats with counts and top vendors.
    """
    from sqlmodel import func

    vendor_count = session.exec(select(func.count()).select_from(LLMOrg)).one()
    model_count = session.exec(
        select(func.count()).select_from(LargeLanguageModel)
    ).one()
    deployment_count = session.exec(
        select(func.count()).select_from(LLMDeployment)
    ).one()
    price_count = session.exec(select(func.count()).select_from(LLMPrice)).one()

    # Get top vendors by model count
    top_vendors_result = session.exec(
        select(
            LLMOrg.name,
            func.count(LargeLanguageModel.id).label("model_count"),
        )
        .join(LargeLanguageModel, isouter=True)
        .group_by(LLMOrg.id)
        .order_by(func.count(LargeLanguageModel.id).desc())
        .limit(10)
    ).all()

    return CatalogStats(
        vendor_count=vendor_count,
        model_count=model_count,
        deployment_count=deployment_count,
        price_count=price_count,
        top_vendors=list(top_vendors_result),
    )
