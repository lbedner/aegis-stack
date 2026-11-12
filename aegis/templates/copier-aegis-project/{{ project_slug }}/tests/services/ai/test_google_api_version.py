"""Google's speech, voice-library and live models are on its v1beta API;
google-genai 3 builds every client for v1 unless told otherwise."""

import pytest

genai = pytest.importorskip("google.genai")

import app.services.ai  # noqa: E402,F401


def test_a_google_client_asks_the_api_its_voice_models_are_on() -> None:
    client = genai.Client(api_key="test-key")

    assert client._api_client._http_options.api_version == "v1beta"
