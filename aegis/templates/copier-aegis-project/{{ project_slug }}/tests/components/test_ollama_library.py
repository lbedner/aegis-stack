"""Ollama's pulled models, linked into a llama.cpp router's folder
(``app.components.inference.ollama_library``): one pull serves both engines
from one file, and what llama.cpp cannot load is left out."""

from pathlib import Path
import shutil
import subprocess

import pytest

from app.components.inference import ollama_library
from app.components.inference.ollama_library import link_ollama, ollama_models
from tests._fake_ollama import pulled

TENSOR = "application/vnd.ollama.image.tensor"  # an MLX model's layers


def test_ollama_names_its_gguf_models_and_not_its_mlx_ones(tmp_path: Path) -> None:
    gguf = pulled(tmp_path, "registry.ollama.ai/library/qwen", "7b", b"GGUF1")
    pulled(tmp_path, "registry.ollama.ai/library/qwen", "7b-mlx", b"x", TENSOR)
    hub = pulled(tmp_path, "hf.co/someone/tiny", "Q4", b"GGUF2")

    assert ollama_models(tmp_path) == {"qwen:7b": gguf, "hf.co/someone/tiny:Q4": hub}


def test_each_model_is_linked_once_and_nothing_is_overwritten(tmp_path: Path) -> None:
    """A name already in the folder (the user's own file) stays; a file
    already there under another name is not listed twice; a link to a
    model Ollama has since removed goes."""
    ollama, folder = tmp_path / "ollama", tmp_path / "models"
    qwen = pulled(ollama, "registry.ollama.ai/library/qwen", "7b", b"GGUF1")
    mine = pulled(ollama, "registry.ollama.ai/library/mine", "1b", b"GGUF2")
    llama = pulled(ollama, "registry.ollama.ai/library/llama", "8b", b"GGUF3")
    hub = pulled(ollama, "hf.co/someone/tiny", "Q4", b"GGUF4")
    folder.mkdir()
    (folder / "mine:1b.gguf").write_bytes(b"GGUF-users-own")
    (folder / "renamed.gguf").symlink_to(llama)
    (folder / "gone:1b.gguf").symlink_to(ollama / "blobs" / "sha256-gone")

    linked = link_ollama(folder, ollama)

    assert linked == ["hf.co/someone/tiny:Q4", "qwen:7b"]
    assert (folder / "qwen:7b.gguf").resolve() == qwen.resolve()
    assert (folder / "hf.co--someone--tiny:Q4.gguf").resolve() == hub.resolve()
    assert (folder / "mine:1b.gguf").read_bytes() == b"GGUF-users-own"
    assert not (folder / "gone:1b.gguf").is_symlink()
    assert mine.exists() and link_ollama(folder, ollama) == []


@pytest.fixture(autouse=True)
def llama_reads_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fakes here are no models: llama.cpp, where it is installed, would
    refuse every one (the check has its own tests below)."""
    monkeypatch.setattr(ollama_library, "llama_reads", lambda blob: True)


def test_a_model_llama_cpp_cannot_load_is_not_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ollama writes some files in a form llama.cpp rejects (gpt-oss's
    architecture, qwen3.6's rope sections): llama.cpp lists such a link and
    fails to load it. It is left out, and a link made to it before goes."""
    ollama, folder = tmp_path / "ollama", tmp_path / "models"
    oss = pulled(ollama, "registry.ollama.ai/library/gpt-oss", "20b", b"GGUF-oss")
    pulled(ollama, "registry.ollama.ai/library/qwen", "7b", b"GGUF-qwen")
    folder.mkdir()
    (folder / "gpt-oss:20b.gguf").symlink_to(oss)
    monkeypatch.setattr(ollama_library, "llama_reads", lambda blob: blob != oss)

    assert link_ollama(folder, ollama) == ["qwen:7b"]
    assert not (folder / "gpt-oss:20b.gguf").is_symlink()


@pytest.mark.parametrize(
    ("installed", "exit_code", "reads"),
    [(True, 0, True), (True, 1, False), (False, None, True)],
)
def test_llama_cpp_itself_says_what_it_loads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    installed: bool,
    exit_code: int | None,
    reads: bool,
) -> None:
    """Its own ``llama-fit-params`` reads a model's settings as a load does,
    without its weights; where llama.cpp is not installed, nothing can be
    checked and the file is taken."""
    monkeypatch.undo()
    ran: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, exit_code or 0)

    monkeypatch.setattr(
        shutil, "which", lambda name: f"/bin/{name}" if installed else None
    )
    monkeypatch.setattr(subprocess, "run", run)

    assert ollama_library.llama_reads(tmp_path / "m.gguf") is reads
    assert [a[:3] for a in ran] == (
        [["/bin/llama-fit-params", "-m", str(tmp_path / "m.gguf")]] if installed else []
    )
