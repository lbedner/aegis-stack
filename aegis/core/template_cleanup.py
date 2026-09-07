"""
Template cleanup utilities for post-update processing.

This module handles cleanup tasks after Copier updates, particularly
dealing with nested directory structures created during template updates.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..constants import AnswerKeys
from .verbosity import verbose_print


def _killed_by_signal(returncode: int) -> bool:
    """True when a process was killed by a signal rather than exiting normally.

    Under memory pressure the OS OOM-kills child processes (e.g. ``ruff``),
    which surfaces as a negative return code (POSIX ``-SIGKILL``) or the
    shell-style ``128 + signal`` (137 = SIGKILL, 139 = SIGSEGV). That's a
    transient resource failure, NOT a genuine tool error (ruff/git use small
    exit codes like 1/2), so it's safe to retry.
    """
    return returncode < 0 or returncode >= 128


def run_resilient(
    args: list[str],
    *,
    retries: int = 3,
    backoff: float = 0.5,
    retry_on_signal_kill: bool = False,
    **kwargs: object,
) -> subprocess.CompletedProcess[bytes]:
    """``subprocess.run`` that retries transient failures under heavy load.

    Fork failures (``OSError`` — e.g. EAGAIN / too many open files) and
    timeouts happen when many parallel ``uv``/``git``/``ruff`` subprocesses
    contend for a starved machine; a brief backoff usually clears them. With
    ``retry_on_signal_kill=True``, a process killed by a signal (OOM-kill etc.)
    is also retried. Genuine tool errors (a small non-zero return code) are
    NEVER retried — they come back as a normal ``CompletedProcess`` for the
    caller to interpret, so happy-path behavior is unchanged. Re-raises the
    last transient exception if every attempt fails.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            proc = subprocess.run(args, **kwargs)  # type: ignore[call-overload]
        except (OSError, subprocess.SubprocessError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
            continue
        if (
            retry_on_signal_kill
            and _killed_by_signal(proc.returncode)
            and attempt < retries
        ):
            time.sleep(backoff * (attempt + 1))
            continue
        return proc
    assert last_exc is not None
    raise last_exc


def normalize_for_compare(text: str) -> str:
    """Canonicalize text for divergence comparison.

    Strips per-line trailing whitespace and trailing blank lines, and
    normalizes line endings. This absorbs whitespace-only differences
    between a file as Copier wrote it and a re-render of the same template
    (Jinja configuration differences surface as blank-line whitespace).
    """
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def ruff_executable(project_path: Path | None = None) -> str | None:
    """Locate a ruff binary, preferring the target project's own.

    Init formats every generated file with the *project's* pinned ruff
    (post-gen ``make fix`` runs inside the project), so producing output
    that matches init byte-for-byte requires the same binary. The tool's
    own ruff is a floating dependency and can resolve to a formatter with
    different output; formatting a project's files with it reintroduces
    the add/regen drift the byte-identity tests guard against.

    Falls back to the running interpreter's ruff, then PATH. Returns None
    if nothing is found (callers then bias toward preserving the file
    rather than overwriting it).
    """
    if project_path is not None:
        for rel in ("bin/ruff", "Scripts/ruff.exe"):
            candidate = project_path / ".venv" / rel
            if candidate.is_file():
                return str(candidate)
    candidate = Path(sys.executable).parent / "ruff"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("ruff")


def run_ruff_on_text(
    src: str,
    project_path: Path,
    check_select: str | None,
    rel_path: str | None = None,
) -> str | None:
    """Run ruff over ``src`` and return the result, or None on any failure.

    ``check_select`` controls the ``ruff check --fix`` step that runs
    before ``ruff format``:
      - ``""``  → check with the project's configured rule set (used for
        equality comparison, where matching ``make fix`` exactly matters;
        the result must never be written to disk because destructive rules
        like unused-import removal are in play).
      - a value like ``"I"`` → check with only those rules (used before a
        merge, where we must NOT delete code — isort never removes).
      - ``None`` → skip check entirely, format only.

    ``src`` is piped over stdin with ``--stdin-filename`` set to ``rel_path``
    (the file's project-relative path) and ``cwd=project_path``, so ruff
    resolves the project's ``[tool.ruff]`` config AND applies its
    ``per-file-ignores`` as if the content lived at the real path. The old
    temp-file approach ran under a random name, which silently dropped
    path-keyed rules — e.g. deps.py's F401 ignore — so regen deleted that
    file's intentional re-export imports (issue #814 audit).
    """
    ruff = ruff_executable(project_path)
    if ruff is None:
        return None
    stdin_name = rel_path or "__aegis_ruff_normalize__.py"
    current = src
    steps: list[list[str]] = []
    if check_select == "":
        steps.append([ruff, "check", "--fix", "--quiet"])
    elif check_select is not None:
        steps.append([ruff, "check", "--fix", "--select", check_select, "--quiet"])
    steps.append([ruff, "format", "--quiet"])
    try:
        for args in steps:
            proc = run_resilient(
                [*args, "--stdin-filename", stdin_name, "-"],
                cwd=str(project_path),
                input=current.encode("utf-8"),
                capture_output=True,
                timeout=30,
                retry_on_signal_kill=True,
                # A merged .py file spawns ~6 ruff subprocesses; under a
                # parallel test/CI run that contends with uv/git/copier,
                # fork failures (EAGAIN) and timeouts spike briefly. A
                # wider retry budget rides out the spike instead of
                # silently degrading the merge to preserve+warn.
                retries=5,
                backoff=1.0,
            )
            # ``ruff check --fix`` exits 1 when fixable issues remain after
            # fixing (normal — e.g. unfixable lint rules); only >=2 is a
            # real error (bad config, unreadable file). ``ruff format``
            # exits non-zero only on error (e.g. unparseable input). Either
            # way, bail to None so the caller preserves the file rather than
            # acting on partially/unformatted output.
            is_format = args[1] == "format"
            if (is_format and proc.returncode != 0) or (
                not is_format and proc.returncode >= 2
            ):
                return None
            current = proc.stdout.decode("utf-8")
        return current
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class SyncResult:
    """Result of sync_template_changes() with details about what happened."""

    synced: list[str] = field(default_factory=list)
    """Files updated (clean merge or overwrite)."""

    conflicts: list[str] = field(default_factory=list)
    """Files with merge conflict markers that need manual resolution."""

    answers_backfilled: list[str] = field(default_factory=list)
    """Answer keys added to .copier-answers.yml because the target template
    version introduced them (e.g. ``postgres_provider`` in 0.9.0)."""

    removed: list[str] = field(default_factory=list)
    """Files deleted because the target template no longer ships them and the
    project had not customized them."""

    stale: list[str] = field(default_factory=list)
    """Files the target template no longer ships that were customized, so they
    were KEPT. They are dead code the project still carries — and when the
    replacement is a package of the same name, the leftover module is shadowed,
    so those customizations have silently stopped running."""


def _reconcile_new_answer_keys(project_path: Path, new_rendered_dir: Path) -> list[str]:
    """Backfill answer keys the target template records but the project lacks.

    aegis preserves the project's existing ``.copier-answers.yml`` across an
    update — copier's own answer write-back is unreliable for
    ``{{ project_slug }}``-wrapped projects, so we sync files ourselves. A
    consequence is that a question ADDED in the target version (e.g.
    ``postgres_provider`` in 0.9.0) never lands in the project's answers file,
    even though copier rendered it with its default. The freshly rendered
    template (``new_rendered_dir``, produced from the real template source at
    the target ref — GitHub in production) carries the authoritative value, so
    copy any non-private key that's absent from the project's answers. Without
    this, downstream steps (``_advance_copier_tracking``, the next
    ``aegis update``, ``aegis add``) silently re-default the missing question
    and never gate on the user's real configuration.

    Private (``_``-prefixed) keys are owned by copier tracking and skipped.
    Backfilling is best-effort: on a read/parse/write failure or a
    non-mapping answers file (both files are normally copier-rendered
    mappings, but one may be hand-edited or corrupt), warn and return ``[]``
    rather than aborting the update.
    """
    project_answers_file = project_path / AnswerKeys.ANSWERS_FILENAME
    new_answers_file = new_rendered_dir / AnswerKeys.ANSWERS_FILENAME
    if not project_answers_file.exists() or not new_answers_file.exists():
        return []

    try:
        project_answers = yaml.safe_load(project_answers_file.read_text())
        new_answers = yaml.safe_load(new_answers_file.read_text())
    except (OSError, yaml.YAMLError, ValueError) as e:
        # ValueError covers UnicodeDecodeError from a non-UTF-8 file.
        verbose_print(f"   Warning: Could not read answers for backfill: {e}")
        return []

    # An empty file parses to None; a list/scalar to a non-dict. Either way
    # there's nothing to reconcile against — don't crash on ``.items()``.
    project_answers = project_answers or {}
    if not isinstance(project_answers, dict) or not isinstance(new_answers, dict):
        return []

    added: list[str] = []
    for key, value in new_answers.items():
        if key.startswith("_"):
            continue
        if key not in project_answers:
            project_answers[key] = value
            added.append(key)

    if added:
        try:
            project_answers_file.write_text(
                yaml.safe_dump(
                    project_answers, default_flow_style=False, sort_keys=False
                )
            )
        except OSError as e:
            verbose_print(f"   Warning: Could not write backfilled answers: {e}")
            return []
    return added


def cleanup_nested_project_directory(
    project_path: Path,
    project_slug: str,
) -> list[str]:
    """
    Move files from nested project_slug directory up to project root.

    This handles Copier's behavior during updates where NEW files
    get created with {{ project_slug }}/ prefix. The template uses
    a {{ project_slug }}/ wrapper directory, which Copier renders
    during updates, creating nested paths like:

        project/project_slug/new_file.py

    This function moves such files to their correct location:

        project/new_file.py

    Args:
        project_path: Path to project root
        project_slug: The project slug (from .copier-answers.yml)

    Returns:
        List of relative file paths that were moved
    """
    if not project_slug:
        return []

    nested_dir = project_path / project_slug

    if not nested_dir.exists() or not nested_dir.is_dir():
        return []

    files_moved: list[str] = []

    # Collect all files first (avoid modifying while iterating)
    files_to_move: list[tuple[Path, Path]] = []

    for item in nested_dir.rglob("*"):
        if item.is_dir():
            continue

        # Calculate destination path
        relative = item.relative_to(nested_dir)
        dest = project_path / relative

        files_to_move.append((item, dest))

    # Move files
    for source, dest in files_to_move:
        try:
            # Create parent directories if needed
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Skip files that already exist — sync_template_changes() will
            # handle them with a proper 3-way merge that preserves user
            # customizations. Only move truly NEW files here.
            if dest.exists():
                source.unlink()
                verbose_print(
                    f"   Skipped (exists, will merge): {dest.relative_to(project_path)}"
                )
                continue

            shutil.move(str(source), str(dest))

            relative_path = str(dest.relative_to(project_path))
            files_moved.append(relative_path)
            verbose_print(f"   Moved: {relative_path}")
        except (OSError, shutil.Error) as e:
            raise RuntimeError(f"Failed to move {source} to {dest}: {e}") from e

    # Remove the nested directory tree (non-critical cleanup)
    if nested_dir.exists():
        try:
            shutil.rmtree(nested_dir)
            verbose_print(f"   Removed nested directory: {project_slug}/")
        except (OSError, shutil.Error):
            # Non-critical: nested dir removal is just cleanup
            verbose_print(f"   Warning: Could not remove {project_slug}/")

    return files_moved


def sync_template_changes(
    project_path: Path,
    answers: dict,
    template_src: str,
    vcs_ref: str,
    template_changed_files: set[str] | None = None,
    old_commit: str | None = None,
) -> SyncResult:
    """
    Sync template changes using 3-way merge to preserve user customizations.

    Copier's update mechanism uses `git apply` which is non-functional for
    Aegis projects due to the {{ project_slug }}/ wrapper causing path
    mismatches. This function is the primary mechanism for updating project
    files.

    It performs a 3-way merge for each changed file:
    - **Base**: Old template render (what the project was originally generated from)
    - **Current**: User's project file (may have customizations)
    - **Other**: New template render (the update target)

    Decision logic per file:
    1. Old template doesn't exist → new file → write new version
    2. Old template == user's file → user didn't customize → safe overwrite
    3. Old template == new template → template didn't change → skip
    4. All three differ → 3-way merge via `git merge-file`

    Note: This function only syncs EXISTING files. New files are handled by
    cleanup_nested_project_directory() which must run BEFORE this function.

    Args:
        project_path: Path to project root
        answers: Copier answers dict (from .copier-answers.yml)
        template_src: Template source (e.g., "gh:user/repo")
        vcs_ref: Git ref for template version (e.g., "v0.5.3-rc1")
        template_changed_files: Set of project-relative file paths that
            actually changed in the template between versions. When provided,
            only these files are eligible for sync.
        old_commit: Git ref for the OLD template version (from _commit in
            .copier-answers.yml). Used to render the base version for 3-way merge.

    Returns:
        SyncResult with lists of synced files and files with conflicts.
    """
    from copier import run_copy

    project_slug = answers.get("project_slug", "")
    if not project_slug:
        return SyncResult()

    result = SyncResult()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        new_render = temp_path / "new"
        old_render = temp_path / "old"

        # Render the NEW template version
        try:
            run_copy(
                src_path=template_src,
                dst_path=str(new_render),
                data=answers,
                defaults=True,
                overwrite=True,
                unsafe=False,
                vcs_ref=vcs_ref,
                quiet=True,
            )
        except Exception as e:
            verbose_print(f"   Warning: Could not render new template for sync: {e}")
            return SyncResult()

        new_rendered_dir = new_render / project_slug
        if not new_rendered_dir.exists():
            return SyncResult()
        _prune_render(new_rendered_dir, answers)

        # Render the OLD template version (for 3-way merge base)
        old_rendered_dir: Path | None = None
        if old_commit:
            try:
                run_copy(
                    src_path=template_src,
                    dst_path=str(old_render),
                    data=answers,
                    defaults=True,
                    overwrite=True,
                    unsafe=False,
                    vcs_ref=old_commit,
                    quiet=True,
                )
                candidate = old_render / project_slug
                if candidate.exists():
                    _prune_render(candidate, answers)
                    old_rendered_dir = candidate
            except Exception as e:
                verbose_print(
                    f"   Warning: Could not render old template for merge base: {e}"
                )
                # Fall back to overwrite behavior (no old render available)

        # Compare and sync files
        for template_file in new_rendered_dir.rglob("*"):
            if template_file.is_dir():
                continue

            relative = template_file.relative_to(new_rendered_dir)
            if _should_skip_sync(str(relative)):
                continue

            project_file = project_path / relative

            # Only sync files the template actually changed between versions
            if (
                template_changed_files is not None
                and relative.as_posix() not in template_changed_files
            ):
                continue

            try:
                new_content = template_file.read_bytes()

                # A file the template ships that the project doesn't have yet.
                # cleanup_nested_project_directory() normally creates it from
                # Copier's nested output — but Copier sometimes merges a new
                # module's importers into existing files while failing to
                # materialize the module itself, leaving a broken import graph
                # (issue #775). When we have a changed-set, this file passed
                # that filter above, so it's a genuine template addition for
                # this version; create it from the new render as the reliable
                # backstop. Without a changed-set (git diff failed) we can't
                # tell an addition from a file the user deleted on purpose, so
                # we defer to cleanup_nested and skip.
                if not project_file.exists():
                    if template_changed_files is None:
                        verbose_print(f"   Skipped new file: {relative}")
                        continue
                    project_file.parent.mkdir(parents=True, exist_ok=True)
                    project_file.write_bytes(new_content)
                    result.synced.append(str(relative))
                    verbose_print(f"   Created new file: {relative}")
                    continue

                project_content = project_file.read_bytes()

                # No difference — nothing to do
                if new_content == project_content:
                    continue

                old_file = old_rendered_dir / relative if old_rendered_dir else None

                if old_file and old_file.exists():
                    old_content = old_file.read_bytes()

                    if old_content == project_content:
                        # User didn't customize — safe to use new version
                        project_file.write_bytes(new_content)
                        result.synced.append(str(relative))
                        verbose_print(f"   Synced: {relative}")
                    elif old_content == new_content:
                        # Template didn't change this file — keep user's version
                        verbose_print(f"   Preserved: {relative} (user customized)")
                        continue
                    elif project_file.name.endswith(".py") and _sync_python_file(
                        project_file,
                        old_file,
                        template_file,
                        relative,
                        result,
                        project_path,
                    ):
                        # Handled with formatting awareness: init-time
                        # ``make fix`` reformats project files, so a byte
                        # comparison against the raw renders misreads
                        # formatting as user edits (spurious conflicts).
                        continue
                    else:
                        # All three differ — 3-way merge
                        _three_way_merge(
                            project_file, old_file, template_file, relative, result
                        )
                else:
                    # No base render for this file — without the old version we
                    # can't tell a user customization from a template change, so
                    # overwriting risks silent data loss (issue #773). Preserve
                    # the user's file, drop the new render beside it as a ``.rej``
                    # (the same convention Copier conflicts use, so
                    # ``analyze_conflict_files`` surfaces it in the report), and
                    # report a conflict rather than a silent sync.
                    rej_file = project_file.with_name(project_file.name + ".rej")
                    rej_file.write_bytes(new_content)
                    result.conflicts.append(str(relative))
                    verbose_print(
                        f"   No merge base — preserved {relative}, "
                        f"template version written to {relative}.rej"
                    )

            except OSError as e:
                verbose_print(f"   Warning: Could not sync {relative}: {e}")

        # Second pass: files the target template DROPPED. The loop above walks
        # the new render, so a deleted file is invisible to it and survives
        # forever - a module renamed to a package of the same name leaves the
        # old file shadowed but present, which is valid code nobody runs.
        _remove_dropped_files(project_path, old_rendered_dir, new_rendered_dir, result)

        # Backfill answer keys the target version added (the answers file
        # itself is skipped by the content sync above). Must run inside the
        # temp-dir block while the rendered answers file still exists.
        result.answers_backfilled = _reconcile_new_answer_keys(
            project_path, new_rendered_dir
        )
        for key in result.answers_backfilled:
            verbose_print(f"   Backfilled new answer: {key}")

    return result


def _prune_render(rendered_dir: Path, answers: dict[str, Any]) -> None:
    """Make a raw render look like init's output for this stack.

    The template carries every component; ``aegis init`` prunes what the
    answers did not select. Comparing against the unpruned render made the
    create-missing-file backstop resurrect storage, documents, and blog
    files in a project that has none of them, moments after component
    cleanup had removed them. Pruning both renders keeps every comparison
    on the file set this stack actually owns.
    """
    from aegis.core.post_gen_tasks import cleanup_components  # circular at module load

    cleanup_components(rendered_dir, answers)


def _remove_dropped_files(
    project_path: Path,
    old_rendered_dir: Path | None,
    new_rendered_dir: Path,
    result: SyncResult,
) -> None:
    """Delete project files the target template no longer ships.

    Walks the OLD render - the mirror of the sync loop - and deletes anything
    absent from the new one. Three guards, each load-bearing:

    * **No old render, no deletions.** Without a base there is no way to tell
      "the template dropped this" from "the user added this", and guessing
      wrong destroys work. The merge path degrades to overwrite semantics when
      the old render fails; this path has to stop entirely.
    * **Both renders use the same answers.** A file missing because a component
      is switched off is missing from BOTH, so component footprints are never
      deletion candidates - only genuine template removals are.
    * **Content must still match the old render.** The same customization test
      the 3-way merge applies. An edited file is kept and reported instead,
      because a rename means its edits have stopped running and the user needs
      to hear that, not lose the evidence.
    """
    if old_rendered_dir is None:
        return

    removed_paths: list[Path] = []
    for old_file in sorted(old_rendered_dir.rglob("*")):
        if old_file.is_dir():
            continue
        relative = old_file.relative_to(old_rendered_dir)
        if _should_skip_sync(str(relative)):
            continue
        if (new_rendered_dir / relative).exists():
            continue
        project_file = project_path / relative
        if not project_file.exists():
            continue
        try:
            if not _unedited(project_file, old_file, relative, project_path):
                result.stale.append(str(relative))
                verbose_print(
                    f"   Kept customized file no longer in template: {relative}"
                )
                continue
            project_file.unlink()
        except OSError as e:
            verbose_print(f"   Warning: Could not remove {relative}: {e}")
            continue
        result.removed.append(str(relative))
        removed_paths.append(project_file)
        verbose_print(f"   Removed file no longer in template: {relative}")

    # Prune directories the deletions emptied, deepest first so a nested tree
    # collapses in one pass. Stale bytecode does not count as content: init
    # imports what it generates, so every package carries a ``__pycache__``,
    # and a moved package kept alive by its .pyc files is still a package.
    for parent in sorted(
        {p.parent for p in removed_paths}, key=lambda p: len(p.parts), reverse=True
    ):
        current = parent
        while current != project_path and current.is_relative_to(project_path):
            try:
                if not current.exists() or not _only_bytecode(current):
                    break
                shutil.rmtree(current)
                verbose_print(
                    f"   Removed empty directory: {current.relative_to(project_path)}"
                )
            except OSError:
                break
            current = current.parent


def _only_bytecode(directory: Path) -> bool:
    """True when nothing but ``__pycache__`` trees remain under ``directory``."""
    return all(
        entry.is_dir() and entry.name == "__pycache__" for entry in directory.iterdir()
    )


def _unedited(
    project_file: Path, old_file: Path, relative: Path, project_path: Path
) -> bool:
    """Is the project file the old render, give or take formatting?

    ``aegis init`` post-gen ruff-formats every file, so a byte comparison
    against the raw render calls every formatted module "customized". For
    Python that is the same look-through-formatting test the sync loop
    applies; anything else is compared byte-wise. Ruff unavailable means
    the conservative answer: treat as edited.
    """
    project_bytes, old_bytes = project_file.read_bytes(), old_file.read_bytes()
    if project_bytes == old_bytes:
        return True
    if relative.suffix != ".py":
        return False
    rel = relative.as_posix()
    project_norm = run_ruff_on_text(
        project_bytes.decode("utf-8"), project_path, "", rel_path=rel
    )
    old_norm = run_ruff_on_text(
        old_bytes.decode("utf-8"), project_path, "", rel_path=rel
    )
    if project_norm is None or old_norm is None:
        return False
    return normalize_for_compare(project_norm) == normalize_for_compare(old_norm)


def _warn_raw_merge_fallback(relative: Path) -> None:
    """Warn visibly (not just in verbose mode) that a Python merge degraded.

    Routed to stderr unconditionally: a silent degrade here is exactly what
    made the 0.9.1rc3 conflicts undiagnosable from the user's terminal.
    """
    print(
        f"   Warning: ruff unavailable/failed for {relative}; "
        "falling back to raw merge (formatting may read as edits)",
        file=sys.stderr,
    )


def _sync_python_file(
    project_file: Path,
    old_file: Path,
    new_file: Path,
    relative: Path,
    result: SyncResult,
    project_path: Path,
) -> bool:
    """Sync a Python file whose three versions all differ, looking through
    formatting.

    ``aegis init`` post-gen runs ``make fix``, so project files are
    ruff-formatted while the old/new template renders are raw Jinja output
    (blank-line runs from unselected ``{% if %}`` blocks, unsorted imports).
    Compared byte-wise that formatting reads as user edits, turning a
    pristine file into a merge with conflicts wherever real template
    changes land near the formatting differences. Mirrors the add/remove
    path's fix for issue #715 (``render_diff.RenderDiffEngine._merge``).

    Returns True when the file was handled (synced, preserved, merged, or
    genuinely conflicted after a normalized merge); False when ruff or git
    is unavailable, so the caller falls back to the raw 3-way merge.
    """
    project_text = project_file.read_text(encoding="utf-8")
    old_text = old_file.read_text(encoding="utf-8")

    # Full-rule normalization matches what ``make fix`` did to the project
    # file at init; comparison only, never written to disk.
    rel = relative.as_posix()
    project_norm = run_ruff_on_text(project_text, project_path, "", rel_path=rel)
    old_norm = run_ruff_on_text(old_text, project_path, "", rel_path=rel)
    if project_norm is None or old_norm is None:
        _warn_raw_merge_fallback(relative)
        return False

    if normalize_for_compare(project_norm) == normalize_for_compare(old_norm):
        # Pristine: the project file differs from the old render only by
        # formatting. Take the new render wholesale; post-gen formatting
        # reformats it after a conflict-free update.
        project_file.write_bytes(new_file.read_bytes())
        result.synced.append(str(relative))
        verbose_print(f"   Synced: {relative} (pristine, formatting-only drift)")
        return True

    new_text = new_file.read_text(encoding="utf-8")
    new_norm = run_ruff_on_text(new_text, project_path, "", rel_path=rel)
    if new_norm is not None and normalize_for_compare(old_norm) == (
        normalize_for_compare(new_norm)
    ):
        # The template change is formatting-only noise — keep the user's file.
        verbose_print(f"   Preserved: {relative} (template change is format-only)")
        return True

    # Real user edit AND real template change: merge import-sorted and
    # formatted versions of all three sides so formatting noise cannot
    # conflict. ``--select I`` never deletes code, so the normalized ours
    # side is safe to write back to disk.
    project_safe = run_ruff_on_text(project_text, project_path, "I", rel_path=rel)
    old_safe = run_ruff_on_text(old_text, project_path, "I", rel_path=rel)
    new_safe = run_ruff_on_text(new_text, project_path, "I", rel_path=rel)
    if project_safe is None or old_safe is None or new_safe is None:
        _warn_raw_merge_fallback(relative)
        return False

    returncode, merged = merge_three_way_text(project_safe, old_safe, new_safe)
    if returncode == 0:
        project_file.write_text(merged, encoding="utf-8")
        result.synced.append(str(relative))
        verbose_print(f"   Merged: {relative}")
        return True
    if 1 <= returncode <= 127:
        project_file.write_text(merged, encoding="utf-8")
        result.conflicts.append(str(relative))
        verbose_print(f"   Conflict (needs manual review): {relative}")
        return True
    return False  # git merge-file unavailable/errored — raw fallback


def merge_three_way_text(current: str, base: str, other: str) -> tuple[int, str]:
    """Run a 3-way merge on three text blobs via ``git merge-file``.

    ``current`` is the local file (kept on the "ours" side of any conflict),
    ``base`` is the common ancestor, ``other`` is the incoming version.

    Returns ``(returncode, merged_text)``:
      - ``0``: clean merge, no conflicts.
      - ``1..127``: that many conflicts; ``merged_text`` carries git-style
        conflict markers labelled ``current`` / ``other``.
      - anything else (incl. ``-1`` when git is missing): the merge could
        not run; ``merged_text`` is empty and callers should not write it.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        dp = Path(temp_dir)
        cur, bas, oth = dp / "current", dp / "base", dp / "other"
        cur.write_text(current, encoding="utf-8")
        bas.write_text(base, encoding="utf-8")
        oth.write_text(other, encoding="utf-8")
        try:
            merge = run_resilient(
                [
                    "git",
                    "merge-file",
                    "-p",
                    "-L",
                    "current",
                    "-L",
                    "base",
                    "-L",
                    "other",
                    str(cur),
                    str(bas),
                    str(oth),
                ],
                capture_output=True,
                check=False,
                retry_on_signal_kill=True,
                # Ride out brief fork-failure/timeout spikes under parallel
                # CI load rather than reporting a spurious merge failure
                # that degrades the caller to preserve+warn.
                retries=5,
                backoff=1.0,
            )
        except (OSError, subprocess.SubprocessError):
            return (-1, "")
        return (merge.returncode, merge.stdout.decode("utf-8", errors="replace"))


def _three_way_merge(
    project_file: Path,
    old_file: Path,
    new_file: Path,
    relative: Path,
    result: SyncResult,
) -> None:
    """Perform a 3-way merge using git merge-file.

    Non-conflicting changes from both sides are merged automatically.
    When conflicts exist (both sides changed the same region), the merged
    output with conflict markers is written to the file and reported as a
    conflict for manual resolution, similar to how ``git merge`` behaves.

    This avoids both failure modes of auto-resolution:
    - --ours silently dropped template fixes
    - --theirs silently overwrote user customizations

    Args:
        project_file: User's current file (modified in-place on merge).
        old_file: Old template render (base).
        new_file: New template render (other).
        relative: Relative path for logging/reporting.
        result: SyncResult to append synced/conflict info to.
    """
    merge = subprocess.run(
        [
            "git",
            "merge-file",
            "-p",
            str(project_file),
            str(old_file),
            str(new_file),
        ],
        capture_output=True,
        check=False,
    )
    try:
        if merge.returncode == 0:
            # Clean merge — no conflicts, both sides' changes applied
            project_file.write_bytes(merge.stdout)
            result.synced.append(str(relative))
            verbose_print(f"   Merged: {relative}")
        elif 1 <= merge.returncode <= 127:
            # git merge-file exits with the NUMBER of conflicts (truncated
            # to 127), not a boolean — write merged output with conflict
            # markers directly into the file, just like git merge does
            project_file.write_bytes(merge.stdout)
            result.conflicts.append(str(relative))
            verbose_print(f"   Conflict (needs manual review): {relative}")
        else:
            # Anything else (git's -1/255 error exit, or a negative signal
            # death) means merge-file itself failed and stdout is unreliable.
            # Never overwrite the user's file on error — keep it and surface
            # it for manual review, matching merge_three_way_text semantics.
            result.conflicts.append(str(relative))
            verbose_print(
                f"   Merge error (kept user's version, needs manual review): {relative}"
            )
    except OSError as e:
        verbose_print(f"   Warning: Could not sync {relative}: {e}")


def _should_skip_sync(relative_path: str) -> bool:
    """Check if a file should be skipped during template sync."""
    skip_patterns = [
        AnswerKeys.ANSWERS_FILENAME,
        ".env",
        ".python-version",
        ".venv/",
        "__pycache__/",
        ".git/",
        "*.pyc",
    ]

    for pattern in skip_patterns:
        if pattern.endswith("/"):
            if relative_path.startswith(pattern) or f"/{pattern}" in relative_path:
                return True
        elif pattern.startswith("*"):
            if relative_path.endswith(pattern[1:]):
                return True
        elif relative_path == pattern:
            return True

    return False
