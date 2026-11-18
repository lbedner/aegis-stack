"""Ollama's pulled models, linked into a llama.cpp router's folder
(``app.components.inference.ollama_library``): one pull serves both engines
from one file, and what llama.cpp cannot read is left out."""

from pathlib import Path

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
