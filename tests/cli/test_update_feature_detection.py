"""Tests for ``aegis update``'s on-disk feature detection.

``_detect_existing_features`` reconstructs ``include_*`` flags from the
project structure so that answers files written by older template versions
(missing newer questions) don't cause copier to fall back to ``default:
false`` and delete installed service files on update.

``TestDetectionCharacterization`` pins the behavior that existed before the
detection map was derived from the spec registry — it must keep passing
unchanged. ``TestDetectionFromRegistry`` covers what deriving added: blog /
ingress / observability detection, and a working redis marker (the old map
pointed redis at ``app/components/redis``, which no generated project ever
contained, so redis could never be detected).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.commands.update import _detect_existing_features


def _touch(root: Path, rel: str) -> None:
    """Create a file (or directory for trailing '/') at ``root/rel``."""
    target = root / rel
    if rel.endswith("/"):
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")


class TestDetectionCharacterization:
    """Behavior pinned from the hand-written map. Must never change."""

    def test_empty_project_detects_nothing(self, tmp_path: Path) -> None:
        assert _detect_existing_features(tmp_path) == {}

    def test_only_sets_true_never_false(self, tmp_path: Path) -> None:
        """Missing markers leave flags absent (not False) — the caller merges
        detected flags over the answers file, so an absent key must not
        clobber an existing answer."""
        _touch(tmp_path, "app/services/auth/")
        detected = _detect_existing_features(tmp_path)
        assert detected == {"include_auth": True}
        assert "include_ai" not in detected

    def test_service_markers(self, tmp_path: Path) -> None:
        for rel in (
            "app/services/auth/",
            "app/services/ai/",
            "app/services/comms/",
            "app/services/insights/",
            "app/services/payment/",
        ):
            _touch(tmp_path, rel)
        detected = _detect_existing_features(tmp_path)
        for flag in (
            "include_auth",
            "include_ai",
            "include_comms",
            "include_insights",
            "include_payment",
        ):
            assert detected.get(flag) is True, flag

    def test_component_markers(self, tmp_path: Path) -> None:
        _touch(tmp_path, "app/core/db.py")
        _touch(tmp_path, "app/components/worker/")
        _touch(tmp_path, "app/components/scheduler/")
        detected = _detect_existing_features(tmp_path)
        assert detected.get("include_database") is True
        assert detected.get("include_worker") is True
        assert detected.get("include_scheduler") is True

    @pytest.mark.parametrize(
        "registration",
        [
            "app/services/insights/adapters/collectors/collection.py",
            "app/services/insights/collector_service.py",
        ],
        ids=["current-layout", "pre-restructure-layout"],
    )
    def test_insights_subflags_from_collector_registration(
        self, tmp_path: Path, registration: str
    ) -> None:
        """Sub-flags come from the registration's content, not file
        presence, on the current layout and the one it replaced."""
        _touch(tmp_path, "app/services/insights/")
        collector = tmp_path / registration
        collector.parent.mkdir(parents=True, exist_ok=True)
        collector.write_text("from x import GitHubTrafficCollector, PyPICollector\n")
        detected = _detect_existing_features(tmp_path)
        assert detected["insights_github"] is True
        assert detected["insights_pypi"] is True
        assert detected["insights_plausible"] is False
        assert detected["insights_reddit"] is False


class TestDetectionFromRegistry:
    """Detection gained by deriving the map from spec ``marker_path``s.

    All additions are protective: a flag is only ever flipped to True when
    the component's files are actually on disk, which prevents ``aegis
    update -y`` from re-rendering the project as if the component were never
    installed (and deleting its files).
    """

    def test_blog_detected(self, tmp_path: Path) -> None:
        _touch(tmp_path, "app/services/blog/")
        assert _detect_existing_features(tmp_path).get("include_blog") is True

    def test_ingress_detected(self, tmp_path: Path) -> None:
        _touch(tmp_path, "traefik/")
        assert _detect_existing_features(tmp_path).get("include_ingress") is True

    def test_observability_detected(self, tmp_path: Path) -> None:
        _touch(tmp_path, "app/components/backend/middleware/logfire_tracing.py")
        assert _detect_existing_features(tmp_path).get("include_observability") is True

    def test_redis_detected_via_real_marker(self, tmp_path: Path) -> None:
        """The legacy map pointed redis at ``app/components/redis``, a path no
        generated project contains — redis was undetectable. The spec marker
        points at a file redis actually owns."""
        _touch(tmp_path, "app/components/frontend/dashboard/cards/redis_card.py")
        assert _detect_existing_features(tmp_path).get("include_redis") is True
