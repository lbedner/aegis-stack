"""Sources uploaded to a knowledge base, kept beside the index (its
directory's ``sources/<collection>/``) so they can be read again: where
one is kept, never anywhere else, and letting kept ones go when their
source or collection does (``RAGService.remove_file``, ``delete_collection``,
``rag.sources``'s replace). Blocking file work: off the loop."""

from collections.abc import Iterable
from pathlib import Path, PureWindowsPath
import re

# A collection's name, as Chroma takes one: 3 to 512 characters, a letter
# or digit at each end, no "..". A folder name, so nothing to climb out by.
# Written to read the same as a form field's ``pattern`` (the browser's
# ``v`` flag wants the ``-`` escaped).
PATTERN = r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._\-]{1,510}[A-Za-z0-9]"
COLLECTION = re.compile(PATTERN)
# The same, for people: what a refusal and a form's field both say.
NAMED = (
    "3 or more letters, digits, dots, dashes or underscores, no spaces, "
    "starting and ending with a letter or digit"
)


def check_name(collection: str) -> None:
    """ValueError for a name the index cannot take: said before anything
    is read or embedded, not by Chroma once it all is."""
    if not COLLECTION.fullmatch(collection):
        raise ValueError(f"{collection!r} cannot name a knowledge base: {NAMED}.")


def kept_folder(persist_directory: str, collection: str) -> Path | None:
    """Where uploads to ``collection`` are kept; None for a name no
    collection could have. Its parent is resolved, not the folder: a link
    planted in its place is deleted as a link, never followed."""
    if not COLLECTION.fullmatch(collection):
        return None
    return (Path(persist_directory).parent / "sources").resolve() / collection


def kept_at(persist_directory: str, collection: str, filename: str) -> Path:
    """Where ``filename`` uploaded to ``collection`` is kept: ValueError for
    a name that would land anywhere else."""
    # Either separator, and no drive: ``C:x.md`` would leave the folder.
    name = PureWindowsPath(filename).name
    folder = kept_folder(persist_directory, collection)
    if folder is None or name in ("", ".", "..") or ":" in name:
        raise ValueError(f"Not a place to keep a source: {filename}")
    path = (folder / name).resolve()
    # Resolved, so a link planted to lead out is refused, never written through.
    if not path.is_relative_to(folder):
        raise ValueError(f"Not a place to keep a source: {filename}")
    return path


def keep(path: Path, content: bytes) -> None:
    """Write an upload where ``kept_at`` says it is kept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def forget_kept(sources: Iterable[str], folder: Path) -> None:
    """Delete each of ``sources`` that is an upload kept in ``folder``
    (resolved once, so the file checked is the file deleted)."""
    for source in sources:
        if (kept := Path(source).resolve()).is_relative_to(folder):
            kept.unlink(missing_ok=True)
