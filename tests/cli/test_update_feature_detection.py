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


class TestOllamaModeDetection:
    """``ollama_mode`` is a string answer, and the project already states it.

    A project generated before the question existed has no answer for it, so
    an update rendered with the template default (``none``): the gated
    modules came out empty while the files the project kept still imported
    them, and the failure surfaced as an ImportError at boot. The URL the app
    actually talks to says which mode it is (aegis-stack#1120).
    """

    def _env(self, root: Path, name: str, body: str) -> None:
        (root / name).write_text(body)

    def test_host_url_detects_host(self, tmp_path: Path) -> None:
        self._env(
            tmp_path, ".env", "OLLAMA_BASE_URL=http://host.docker.internal:11434\n"
        )
        assert _detect_existing_features(tmp_path)["ollama_mode"] == "host"

    def test_container_url_detects_docker(self, tmp_path: Path) -> None:
        self._env(tmp_path, ".env", "OLLAMA_BASE_URL=http://ollama:11434\n")
        assert _detect_existing_features(tmp_path)["ollama_mode"] == "docker"

    def test_no_ollama_url_leaves_the_answer_absent(self, tmp_path: Path) -> None:
        """Nothing detected means nothing written — the default already is
        ``none``, and an absent key must never clobber a stored answer."""
        self._env(tmp_path, ".env", "DATABASE_URL=postgresql://localhost/app\n")
        assert "ollama_mode" not in _detect_existing_features(tmp_path)

    def test_commented_out_url_is_not_a_setting(self, tmp_path: Path) -> None:
        self._env(tmp_path, ".env", "# OLLAMA_BASE_URL=http://ollama:11434\n")
        assert "ollama_mode" not in _detect_existing_features(tmp_path)

    def test_falls_back_to_the_example_when_env_is_absent(self, tmp_path: Path) -> None:
        self._env(tmp_path, ".env.example", "OLLAMA_BASE_URL=http://ollama:11434\n")
        assert _detect_existing_features(tmp_path)["ollama_mode"] == "docker"

    def test_real_env_wins_over_the_example(self, tmp_path: Path) -> None:
        """The example is a template artifact; ``.env`` is what the app reads."""
        self._env(
            tmp_path, ".env", "OLLAMA_BASE_URL=http://host.docker.internal:11434\n"
        )
        self._env(tmp_path, ".env.example", "OLLAMA_BASE_URL=http://ollama:11434\n")
        assert _detect_existing_features(tmp_path)["ollama_mode"] == "host"

    def test_unrecognized_url_is_a_host_ollama(self, tmp_path: Path) -> None:
        """Anything that is not the compose service is reached over the
        network, which is what ``host`` means — never ``none``, which would
        strip the Ollama surface from a project actively using it."""
        self._env(tmp_path, ".env", "OLLAMA_BASE_URL=http://10.0.0.4:11434\n")
        assert _detect_existing_features(tmp_path)["ollama_mode"] == "host"


class TestFinanceProviderDetection:
    """The provider flags are written into the project's own settings.

    ``config.py`` renders ``FINANCE_PLAID: bool = True`` or ``False``, so the
    project states the answer outright — reading it back beats defaulting it
    on a project generated before the question existed (aegis-stack#1120).
    """

    def _config(self, root: Path, body: str) -> None:
        path = root / "app" / "core" / "config.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def test_reads_both_flags_off_the_settings_class(self, tmp_path: Path) -> None:
        self._config(
            tmp_path,
            "class Settings:\n"
            "    FINANCE_PLAID: bool = True\n"
            "    FINANCE_SNAPTRADE: bool = False\n",
        )
        detected = _detect_existing_features(tmp_path)
        assert detected["finance_plaid"] is True
        assert detected["finance_snaptrade"] is False

    def test_absent_field_is_left_out_not_guessed(self, tmp_path: Path) -> None:
        """A project with no finance service has no field to read."""
        self._config(tmp_path, "class Settings:\n    DEBUG: bool = False\n")
        detected = _detect_existing_features(tmp_path)
        assert "finance_plaid" not in detected
        assert "finance_snaptrade" not in detected

    def test_no_config_module_detects_nothing(self, tmp_path: Path) -> None:
        assert "finance_plaid" not in _detect_existing_features(tmp_path)
