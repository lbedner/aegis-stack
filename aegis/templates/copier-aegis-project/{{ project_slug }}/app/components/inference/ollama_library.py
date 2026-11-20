"""Ollama's pulled models, linked into a llama.cpp router's folder.

Ollama keeps a pulled model as a manifest (its name, by path) over blobs
named by their hash. A GGUF model has an ``image.model`` layer, a file
llama.cpp reads as it is; an MLX one has only tensor layers, which it
cannot. ``link_ollama`` puts a ``<name>.gguf`` link to each GGUF one in
llama-server's ``--models-dir``, so one pull serves both engines from one
file. It runs on the host, where both live (``inference link-ollama``).
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

GGUF_LAYER = "application/vnd.ollama.image.model"
REGISTRY = "registry.ollama.ai"  # names on it drop the host, and "library/"


def _is_gguf(blob: Path) -> bool:
    try:
        with blob.open("rb") as f:
            return f.read(4) == b"GGUF"
    except OSError:
        return False


def llama_reads(blob: Path) -> bool:
    """Whether the llama.cpp installed here loads ``blob``.

    Ollama writes some GGUF files in a form llama.cpp rejects (gpt-oss's
    architecture under its own name, qwen3.6's rope sections one short),
    and which ones changes with each release of either. So llama.cpp says:
    its ``llama-fit-params`` reads a model's settings as a load does, without
    its weights, in about a tenth of a second. Where llama.cpp is not
    installed, nothing can be checked and the file is taken.
    """
    tool = shutil.which("llama-fit-params")
    if tool is None:
        return True
    try:
        done = subprocess.run(
            [tool, "-m", str(blob), "-c", "512"], capture_output=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def _name(host: str, repo: list[str], tag: str) -> str:
    """The name Ollama lists it by: ``qwen:7b``, ``hf.co/someone/tiny:Q4``."""
    if host == REGISTRY:
        return f"{'/'.join(repo[1:] if repo[0] == 'library' else repo)}:{tag}"
    return f"{host}/{'/'.join(repo)}:{tag}"


def ollama_models(ollama_dir: Path) -> dict[str, Path]:
    """Each GGUF model Ollama has, by its name, to its blob.

    The model layer only: a vision model's projector is left behind, so
    llama.cpp serves it as text (ponytail: an mmproj needs a folder per
    model in ``--models-dir``; link it there when vision is wanted).
    """
    root = ollama_dir / "manifests"
    found: dict[str, Path] = {}
    for manifest in sorted(p for p in root.rglob("*") if p.is_file()):
        host, *repo, tag = manifest.relative_to(root).parts
        try:
            layers = json.loads(manifest.read_text())["layers"]
        except (ValueError, KeyError, OSError):
            continue
        digest = next(
            (
                layer["digest"]
                for layer in layers
                if layer.get("mediaType") == GGUF_LAYER
            ),
            None,
        )
        if not digest or not repo:
            continue
        blob = ollama_dir / "blobs" / digest.replace(":", "-")
        if _is_gguf(blob):
            found[_name(host, repo, tag)] = blob
    return found


def link_ollama(models_dir: Path, ollama_dir: Path) -> list[str]:
    """Link each of Ollama's GGUF models into ``models_dir``; the names
    newly linked, sorted.

    A name already there (the user's own file, or an earlier link) stays as
    it is, and a file already there under another name is not listed a
    second time. A link into Ollama's blobs that is none of these models
    (Ollama removed it, or llama.cpp cannot load it: ``llama_reads``) is removed: the router
    would list a model it cannot load.
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    blobs = (ollama_dir / "blobs").resolve()
    models = {
        name: blob
        for name, blob in ollama_models(ollama_dir).items()
        if llama_reads(blob)
    }
    kept = {blob.resolve() for blob in models.values()}
    for entry in models_dir.iterdir():
        if entry.is_symlink():
            target = Path(os.readlink(entry)).resolve()
            if target.parent == blobs and target not in kept:
                entry.unlink()
    present = {entry.resolve() for entry in models_dir.iterdir()}
    linked = []
    for name, blob in models.items():
        link = models_dir / f"{name.replace('/', '--')}.gguf"
        if link.exists() or link.is_symlink() or blob.resolve() in present:
            continue
        link.symlink_to(blob.resolve())
        linked.append(name)
    return sorted(linked)
