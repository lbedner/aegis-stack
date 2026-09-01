"""Resolving WHO MADE a model from the public model registry.

The catalog's vendor says who serves a model; nothing said who built
it, and inferring that from the id is a name table that goes stale the
week a lab renames a product line (Meta's Muse Glimmer carries no
"llama" anywhere). The registry knows: the org that owns the weights'
repository IS the lab.
"""

from typing import Any

import pytest

from app.services.ai.domains.llm.etl.lab_resolver import (
    pick_repo,
    strip_local_tag,
)


class TestStripLocalTag:
    def test_drops_runner_prefix_tag_and_quantization(self) -> None:
        assert strip_local_tag("ollama/qwen2.5-coder:14b") == "qwen2.5-coder"
        assert strip_local_tag("muse-glimmer:30b-mlx-128k") == "muse-glimmer"
        assert strip_local_tag("gpt-oss:20b") == "gpt-oss"

    def test_leaves_a_plain_id_alone(self) -> None:
        assert strip_local_tag("gpt-5.6-luna") == "gpt-5.6-luna"


def _repo(model_id: str, *, base: Any = None, downloads: int = 0) -> dict[str, Any]:
    return {"modelId": model_id, "downloads": downloads, "base_model": base}


class TestPickRepo:
    def test_a_derivative_yields_to_the_repo_it_derives_from(self) -> None:
        """The most-downloaded hit is often a re-quantizer's upload; it
        names its origin, so the origin is the answer."""
        candidates = [
            _repo("unsloth/Muse-Glimmer-30B-GGUF", base=["meta-models/Muse-Glimmer-30B"], downloads=982_083),
            _repo("meta-models/Muse-Glimmer-30B", downloads=600_273),
        ]
        assert pick_repo(candidates, "muse-glimmer") == "meta-models/Muse-Glimmer-30B"

    def test_an_original_wins_on_name_affinity_not_popularity(self) -> None:
        candidates = [
            _repo("Blackfrost-AI/Muse-Glimmer-30B-Abliterated-GGUF", downloads=9_000_000),
            _repo("meta-models/Muse-Glimmer-30B", downloads=1),
        ]
        assert pick_repo(candidates, "muse-glimmer") == "meta-models/Muse-Glimmer-30B"

    def test_nothing_resembling_the_model_resolves_to_nothing(self) -> None:
        """A local experiment nobody published stays unclaimed rather
        than borrowing a stranger's logo."""
        assert pick_repo([_repo("someone/unrelated-model")], "my-private-merge") is None

    def test_no_candidates_at_all(self) -> None:
        assert pick_repo([], "anything") is None
