"""Resolving WHO MADE a model from the public model registry.

The catalog's vendor says who serves a model; nothing said who built
it, and inferring that from the id is a name table that goes stale the
week a lab renames a product line (Meta's Muse Glimmer carries no
"llama" anywhere). The registry knows: the org that owns the weights'
repository IS the lab.
"""

import base64
from typing import Any

import httpx
import pytest

from app.services.ai.domains.llm.etl import lab_resolver
from app.services.ai.domains.llm.etl.lab_resolver import (
    _org_avatar,
    pick_repo,
    strip_local_tag,
)
from tests._fake_dns import answering, resolving_to


class TestOneOrgOneLookup:
    async def test_a_labs_models_read_its_overview_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sync re-read an org's overview and logo for every one of its
        models; within a run it is read once, however many it made."""
        asked: list[str] = []
        real = httpx.AsyncClient

        def answer(request: httpx.Request) -> httpx.Response:
            asked.append(request.url.path)
            if request.url.path == "/api/models":
                name = request.url.params["search"]
                return httpx.Response(200, json=[{"modelId": f"lab/{name}"}])
            return httpx.Response(200, json={"fullname": "The Lab"})

        def client(**kwargs: Any) -> httpx.AsyncClient:
            return real(transport=httpx.MockTransport(answer), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)
        orgs: dict[str, Any] = {}

        found = [
            await lab_resolver.resolve_lab(name, orgs) for name in ("one", "two")
        ]

        assert [lab.name if lab else None for lab in found] == ["The Lab"] * 2
        assert asked.count("/api/organizations/lab/overview") == 1


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
            _repo(
                "unsloth/Muse-Glimmer-30B-GGUF",
                base=["meta-models/Muse-Glimmer-30B"],
                downloads=982_083,
            ),
            _repo("meta-models/Muse-Glimmer-30B", downloads=600_273),
        ]
        assert pick_repo(candidates, "muse-glimmer") == "meta-models/Muse-Glimmer-30B"

    def test_an_original_wins_on_name_affinity_not_popularity(self) -> None:
        candidates = [
            _repo(
                "Blackfrost-AI/Muse-Glimmer-30B-Abliterated-GGUF", downloads=9_000_000
            ),
            _repo("meta-models/Muse-Glimmer-30B", downloads=1),
        ]
        assert pick_repo(candidates, "muse-glimmer") == "meta-models/Muse-Glimmer-30B"

    def test_nothing_resembling_the_model_resolves_to_nothing(self) -> None:
        """A local experiment nobody published stays unclaimed rather
        than borrowing a stranger's logo."""
        assert pick_repo([_repo("someone/unrelated-model")], "my-private-merge") is None

    def test_no_candidates_at_all(self) -> None:
        assert pick_repo([], "anything") is None


class TestOrgAvatarFetch:
    """The avatar URL comes out of the registry's JSON: someone else's
    choice, so it is fetched only on the public internet (#493)."""

    async def test_an_avatar_on_a_private_address_is_not_fetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["169.254.169.254"])
        sent = answering(monkeypatch, httpx.Response(200, content=b"png"))

        async with httpx.AsyncClient() as client:
            assert await _org_avatar(client, "https://avatars.example/a.png") is None

        assert sent == []

    async def test_a_redirect_to_a_private_address_is_not_followed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"], ["10.0.0.5"])
        sent = answering(
            monkeypatch,
            httpx.Response(302, headers={"location": "https://inside.example/a"}),
            httpx.Response(200, content=b"png"),
        )

        async with httpx.AsyncClient(follow_redirects=True) as client:
            assert await _org_avatar(client, "https://avatars.example/a.png") is None

        assert len(sent) == 1

    async def test_a_public_avatar_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        answering(monkeypatch, httpx.Response(200, content=b"png"))

        async with httpx.AsyncClient() as client:
            icon = await _org_avatar(client, "https://avatars.example/a.png")

        assert icon == base64.b64encode(b"png").decode()
