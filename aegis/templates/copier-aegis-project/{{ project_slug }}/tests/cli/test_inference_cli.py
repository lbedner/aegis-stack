"""``inference``: the speech server as it answers, a line said into an MP3,
and its model unloaded or reloaded; the client the inference API and
Overseer > Inference > Speech call, faked here."""

from pathlib import Path

import pytest

from app.core import speech_server
from tests._cli import invoke
from tests._fake_ollama import SPEECH_READY, speaking


@pytest.fixture(autouse=True)
def llama_reads_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake models here are none llama.cpp would load, where it is
    installed (``ollama_library.llama_reads`` has its own tests)."""
    from app.components.inference import ollama_library

    monkeypatch.setattr(ollama_library, "llama_reads", lambda blob: True)


def test_speech_says_what_the_server_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = SPEECH_READY.model_copy(
        update={"closed": ["ALLOW_DEV_UNLOAD"], "threads": 12}
    )
    speaking(monkeypatch, closed)

    result = invoke(["inference", "speech"])

    assert result.exit_code == 0
    assert "Voices: 2" in result.output
    assert "Threads: 12" in result.output
    assert "General American, female: af_heart" in result.output
    assert "ALLOW_DEV_UNLOAD=true" in result.output


def test_speak_writes_the_line_into_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    said = speaking(monkeypatch)
    out = tmp_path / "hello.mp3"

    result = invoke(["inference", "speak", "Hi.", "-v", "bm_george", "-o", str(out)])

    assert result.exit_code == 0
    assert out.read_bytes() == b"ID3"
    assert said == [("say", "Hi.", "bm_george")]


@pytest.mark.parametrize("action", speech_server.ACTIONS)
def test_speech_model_moves_it(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    done = speaking(monkeypatch)

    assert invoke(["inference", "speech-model", action]).exit_code == 0
    assert done == [("move", action)]


def test_without_a_server_it_says_how_to_set_one() -> None:
    result = invoke(["inference", "speech"])

    assert result.exit_code == 1
    assert "SPEECH_BASE_URL" in result.output


def test_link_ollama_links_its_models_into_the_router_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Into ``LLAMACPP_MODELS_DIR``, from ``OLLAMA_MODELS``; and it says how
    to serve the folder (``make llama``)."""
    from app.core.config import settings
    from tests._fake_ollama import pulled

    pulled(tmp_path / "ollama", "registry.ollama.ai/library/qwen", "7b", b"GGUF")
    monkeypatch.setattr(settings, "OLLAMA_MODELS", str(tmp_path / "ollama"))
    monkeypatch.setattr(settings, "LLAMACPP_MODELS_DIR", str(tmp_path / "models"))

    result = invoke(["inference", "link-ollama"])

    assert result.exit_code == 0
    assert (tmp_path / "models" / "qwen:7b.gguf").is_symlink()
    assert "qwen:7b" in result.output
    assert "make llama" in result.output


def test_link_ollama_without_ollama_says_where_it_looked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "OLLAMA_MODELS", str(tmp_path / "none"))

    result = invoke(["inference", "link-ollama"])

    assert result.exit_code != 0
    assert "OLLAMA_MODELS" in result.output


def test_llama_links_ollama_then_becomes_the_router(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``make llama``: Ollama's models linked in, then the process becomes a
    llama-server router over the folder, on LLAMACPP_BASE_URL's port, at
    LLAMACPP_CONTEXT, with LLAMACPP_ARGS; its terminal is the server's."""
    import os

    from app.components.inference.llamacpp import LlamaCppEngine
    from app.core.config import settings
    from tests._fake_ollama import pulled

    pulled(tmp_path / "ollama", "registry.ollama.ai/library/qwen", "7b", b"GGUF")
    for name, value in {
        "OLLAMA_MODELS": str(tmp_path / "ollama"),
        "LLAMACPP_MODELS_DIR": str(tmp_path / "models"),
        "LLAMACPP_CONTEXT": 65536,
        "LLAMACPP_ARGS": "-np 2 -kvu",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(
        LlamaCppEngine,
        "configured_url",
        classmethod(lambda cls: "http://localhost:8090"),
    )
    became: list[list[str]] = []
    monkeypatch.setattr(os, "execvp", lambda path, argv: became.append(argv))

    result = invoke(["inference", "llama"])

    assert result.exit_code == 0
    assert (tmp_path / "models" / "qwen:7b.gguf").is_symlink()
    assert became == [
        [
            "llama-server",
            "--models-dir",
            str(tmp_path / "models"),
            "--jinja",
            "-c",
            "65536",
            "--metrics",
            "--port",
            "8090",
            "-np",
            "2",
            "-kvu",
        ]
    ]


def test_llama_without_ollama_serves_the_folder_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An install that only ever picks llama.cpp has no Ollama: the folder
    (made if new) and llama.cpp's own downloads are the list."""
    import os

    from app.core.config import settings

    monkeypatch.setattr(settings, "OLLAMA_MODELS", str(tmp_path / "none"))
    monkeypatch.setattr(settings, "LLAMACPP_MODELS_DIR", str(tmp_path / "models"))
    became: list[list[str]] = []
    monkeypatch.setattr(os, "execvp", lambda path, argv: became.append(argv))

    assert invoke(["inference", "llama"]).exit_code == 0
    assert (tmp_path / "models").is_dir() and became
    # Unset, it still starts with what chat needs of it.
    assert type(settings).model_fields["LLAMACPP_ARGS"].default == "-fa on -np 2 -kvu"


@pytest.mark.parametrize(
    ("system", "nvidia", "argv"),
    [
        ("Darwin", None, ["bash", "start-gpu_mac.sh"]),
        ("Linux", "/usr/bin/nvidia-smi", ["bash", "start-gpu.sh"]),
        ("Linux", None, ["bash", "start-cpu.sh"]),
        (
            "Windows",
            "nvidia-smi.exe",
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", "start-gpu.ps1"],
        ),
        (
            "Windows",
            None,
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", "start-cpu.ps1"],
        ),
    ],
)
def test_kokoro_runs_the_checkouts_start_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    system: str,
    nvidia: str | None,
    argv: list[str],
) -> None:
    """``make kokoro``: from SPEECH_SERVER_DIR, the machine's own script, on
    its GPU where it has one (a Mac's, or NVIDIA's), on SPEECH_BASE_URL's
    port, with the two flags the Overseer reads it by; out of this project's
    venv, which its own ``uv`` would install into."""
    import os
    import platform
    import shutil

    from app.core.config import settings

    (tmp_path / argv[-1]).write_text("")
    monkeypatch.setattr(settings, "SPEECH_SERVER_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "SPEECH_BASE_URL", "http://localhost:8890/v1")
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(shutil, "which", lambda name: nvidia)
    monkeypatch.setenv("VIRTUAL_ENV", "/project/.venv")
    ran: list[object] = []
    monkeypatch.setattr(os, "chdir", lambda path: ran.append(path))
    monkeypatch.setattr(
        os, "execvpe", lambda path, args, env: ran.extend([path, args, env])
    )

    assert invoke(["inference", "kokoro"]).exit_code == 0
    folder, path, args, env = ran
    assert (folder, path, args) == (tmp_path, argv[0], argv)
    assert isinstance(env, dict) and "VIRTUAL_ENV" not in env
    assert (env["PORT"], env[speech_server.DEV], env[speech_server.DEBUG]) == (
        "8890",
        "true",
        "true",
    )


def test_kokoro_without_a_checkout_says_how_to_get_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "SPEECH_SERVER_DIR", str(tmp_path / "none"))

    result = invoke(["inference", "kokoro"])

    assert result.exit_code != 0
    assert "SPEECH_SERVER_DIR" in result.output and "git clone" in result.output
