"""Writing one vendor, model, deployment, price or modality row."""

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.core.log import logger

# Re-exported: callers have always reached the catalog readers through
# this module, and moving them out did not move their address.
from app.services.ai.domains.llm.etl.lab_resolver import _grant_role
from app.services.ai.domains.llm.etl.mappers.llm_mapper import (
    MergedLLMData,
)
from app.services.ai.domains.llm.etl.queries import (  # noqa: F401
    CatalogStats,
    catalog_is_populated,
    get_catalog_stats,
    ollama_models_present,
)
from app.services.ai.domains.llm.etl.results import SyncResult
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


class UpsertMixin:
    """The row-level writes the sync passes share.

    Every method here reads ``self.session`` and one of the caches the
    service fills once per run; they are declared so this module type
    checks on its own, and ``LLMSyncService.__init__`` is what actually
    sets them.
    """

    session: Session
    _vendor_cache: dict[str, LLMOrg]
    _model_cache: dict[str, LargeLanguageModel]
    _deployment_cache: dict[tuple[int | None, int | None], LLMDeployment]
    _price_cache: dict[tuple[int | None, int | None], LLMPrice]
    _modality_cache: dict[int | None, dict[tuple[Modality, Direction], LLMModality]]

    def _update_if_changed(self, obj: Any, field: str, new_value: Any) -> bool:
        """Update field if value changed, return True if changed."""
        if getattr(obj, field) != new_value:
            setattr(obj, field, new_value)
            return True
        return False

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
