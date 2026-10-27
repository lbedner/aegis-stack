"""Sources uploaded to a knowledge base: kept beside the index (its
directory's ``sources/<collection>/``), so the index can be read from them
again and nothing uploaded lands anywhere else."""

import asyncio
from pathlib import Path, PureWindowsPath
import re

# A collection's name, as Chroma takes one: 3 to 512 characters, a letter
# or digit at each end, no "..". A folder name, so nothing to climb out by.
COLLECTION = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]")


def kept_at(persist_directory: str, collection: str, filename: str) -> Path:
    """Where ``filename`` uploaded to ``collection`` is kept: ValueError for
    a name that would land anywhere else."""
    # Either separator, and no drive: ``C:x.md`` would leave the folder.
    name = PureWindowsPath(filename).name
    if not COLLECTION.fullmatch(collection) or name in ("", ".", "..") or ":" in name:
        raise ValueError(f"Not a place to keep a source: {collection}/{filename}")
    folder = (Path(persist_directory).parent / "sources" / collection).resolve()
    path = (folder / name).resolve()
    if not path.is_relative_to(folder):  # a link planted to lead out
        raise ValueError(f"Not a place to keep a source: {collection}/{filename}")
    return path


async def keep(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path``, its folders made."""

    def write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    await asyncio.to_thread(write)


async def forget(path: Path) -> None:
    """Remove a kept source that could not be indexed."""
    await asyncio.to_thread(path.unlink, missing_ok=True)
