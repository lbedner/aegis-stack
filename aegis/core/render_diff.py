"""
Answers-diff render engine.

Replaces "does this file need to be on a manual list to regenerate" with
"render the template at the old answers and the new answers, diff the two
renders". A shared file is discovered, not declared: any path where the two
renders differ is, by definition, a file this operation must touch.

Mirrors ``aegis.core.template_cleanup.sync_template_changes`` (which does the
same thing across template *versions* for ``aegis update``) but on the
answers axis instead: same template, old ``.copier-answers.yml`` vs new.

    render(template, old_answers)  -> BASE    (what the project should look like now)
    disk                           -> THEIRS  (what it actually looks like)
    render(template, new_answers)  -> OURS    (what it should look like after the op)

    absent/empty in BASE, present in OURS  -> create
    present in BASE, empty/absent in OURS  -> delete if pristine, else preserve + warn
    BASE == OURS                           -> skip (operation doesn't touch this file),
                                               except missing-on-disk -> create (backfill
                                               for a project that predates this file)
    pristine (THEIRS == BASE)              -> overwrite
    else                                   -> 3-way merge (clean or conflict markers)

A whole-file Jinja gate (``{% if include_x %}...{% endif %}``) renders empty
when its condition is False — templates use full-body wraps, never
conditional filenames — so a file's existence in a given stack falls out of
rendering it, the same way ``manual_updater._is_empty_stub`` already treats
an empty ``.py`` as "not really here".

Two consequences of that worth knowing, both deliberate:

* A gated file that rendered empty still *exists* on disk after init —
  ``{%- if -%}`` emits a newline, and Copier writes the file. That 1-byte
  stub is exactly what the template currently produces, so it is
  **pristine**, and flipping the gate on overwrites it. Comparing the stub
  against OURS instead would misread it as hand-edited and preserve it,
  leaving the file empty forever; for non-``.py`` files nothing would ever
  clean it up, since ``sweep_empty_stubs`` only sweeps ``*.py``.
* Flipping a gate *off* deletes the file rather than truncating it back to
  a stub, so a removal produces a slightly different tree than a fresh
  init without that component (deleted vs. 1-byte stub). Harmless: every
  consumer of such a file is gated on the same flag and regenerates
  alongside it (e.g. the Makefile's ``COMPOSE_PROD`` drops its
  ``-f docker-compose.prod.yml`` when ingress goes away). Don't "fix" this
  by writing stubs — deleting is the cleaner end state.

The residual the diff can't derive is intent — "never touch README even
though it's stack-dependent", "warn, don't merge, the Dockerfile", "no
backup for a derived health dispatcher". That lives on the template file
itself as a ``{#- aegis: <policy> -#}`` comment on its very first line
(see ``FilePolicy``), read and stripped before rendering so it never
reaches project output. The trim markers (``-#`` / ``#-``) are required,
not stylistic — see ``_read_policy_and_body`` for why. No annotation
means the default policy. This is the only per-file override mechanism —
there is no central policy map to keep in sync with the template tree.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .component_files import (
    JINJA_EXTENSION,
    PROJECT_SLUG_PLACEHOLDER,
    _is_skippable_template_file,
)
from .template_cleanup import (
    merge_three_way_text,
    normalize_for_compare,
    run_ruff_on_text,
)


def build_template_env(template_root: Path) -> Environment:
    """The one Jinja environment configuration for rendering aegis templates.

    ``trim_blocks=False`` / ``lstrip_blocks=False`` match Copier's own
    defaults (``copier.yml`` sets no ``_envops``); ``keep_trailing_newline=
    True`` matches what Copier writes at init — without it every
    regenerated file churns its final newline (issue #814 audit). Every
    consumer (``ManualUpdater``, plugin tree rendering, tests) must build
    its environment here, or rendering semantics silently drift between
    init output and regenerated output.
    """
    return Environment(
        loader=FileSystemLoader(str(template_root)),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


class FileAction(str, Enum):
    """What the engine decided to do with one file for this operation."""

    CREATE = "create"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    DELETE = "delete"
    PRESERVE = "preserve"
    """A diverged file the operation would otherwise delete, overwrite, or
    merge, left untouched because policy or a missing merge base says we
    can't safely reconcile it. Reported to the caller like
    ``shared_files_need_manual_merge`` is today."""
    SKIP = "skip"


class FilePolicy(str, Enum):
    """Per-file regeneration policy, read from a ``{# aegis: <word> #}``
    header comment on the template's first line."""

    DEFAULT = "default"
    """No annotation. Overwrite while pristine (with backup), 3-way merge
    once diverged — the behavior every other file gets."""

    USER_OWNED = "user-owned"
    """Create once; never regenerate, merge, or delete afterward — even if
    the operation that seeded it is later undone. For hand-authored prose
    (README, docs) the template only scaffolds (``INTENTIONALLY_NOT_REGENERATED``
    today)."""

    WARN_IF_DIVERGED = "warn-if-diverged"
    """Overwrite while pristine; once hand-edited, preserve and report
    rather than merge — the template only partly owns this file's content
    (issue #870's Dockerfile: the htmx css-build stage is template-owned,
    custom build steps are not, and a merge could mangle them)."""

    NO_BACKUP = "no-backup"
    """Overwrite like DEFAULT, but skip the ``.backup`` copy — for
    derived/transient content nobody hand-edits (health dispatchers,
    db-init hooks)."""


_ANNOTATION_RE = re.compile(
    r"^\{#(?P<open_trim>-)?\s*aegis:\s*(?P<word>[a-zA-Z][a-zA-Z-]*)\s*"
    r"(?P<close_trim>-)?#\}[ \t]*\r?\n?"
)
_ANNOTATABLE = {p.value: p for p in FilePolicy if p is not FilePolicy.DEFAULT}


def _read_policy_and_body(source: str) -> tuple[FilePolicy, str]:
    """Parse and strip a leading ``{#- aegis: <word> -#}`` annotation.

    Returns ``(FilePolicy.DEFAULT, source)`` unchanged when the first line
    isn't an annotation — true for the vast majority of templates.

    Requires Jinja's own whitespace-trim markers on both sides
    (``{#- ... -#}``, not ``{# ... #}``): this comment is still rendered
    by plain Jinja wherever a caller hasn't been rewired onto this engine
    yet (``aegis init`` and ``aegis update`` both render templates via
    Copier/``get_template`` directly, unaware of this annotation). Without
    trim markers, ``trim_blocks=False`` leaves the newline after the
    comment as a literal blank line in the rendered file. With them, the
    comment renders as if it were never there — verified byte-identical
    under the project's exact Jinja ``Environment`` config, so annotating
    a real template is safe *before* any of init/update/add/remove has
    been rewired onto this engine (aegis-stack#919/#920).

    Raises ``ValueError`` on an unrecognized word, or a recognized word
    missing its trim markers, instead of silently falling back to the
    default policy — either mistake must fail loudly, not degrade into
    a default nobody chose.
    """
    match = _ANNOTATION_RE.match(source)
    if match is None:
        return FilePolicy.DEFAULT, source
    word = match.group("word")
    policy = _ANNOTATABLE.get(word)
    if policy is None:
        raise ValueError(
            f"Unknown aegis policy annotation {word!r}; expected one of "
            f"{sorted(_ANNOTATABLE)}"
        )
    if not (match.group("open_trim") and match.group("close_trim")):
        raise ValueError(
            f"aegis policy annotation {word!r} must use Jinja whitespace-trim "
            f"markers on both sides ('{{#- aegis: {word} -#}}'), not "
            f"'{{# aegis: {word} #}}' — without them, plain Jinja rendering "
            "(init, update) leaves a stray blank line where this comment was."
        )
    return policy, source[match.end() :]


@dataclass
class FilePlan:
    """One file's classification, and the content to write if any."""

    rel_path: str
    action: FileAction
    content: str | None = None
    """Content to write for CREATE / OVERWRITE / MERGE. None for DELETE,
    PRESERVE, SKIP."""
    conflict: bool = False
    """True when action is MERGE and the merge produced conflict markers
    (still written to disk, same convention as the update path)."""
    policy: FilePolicy = FilePolicy.DEFAULT


@dataclass
class RenderDiffResult:
    """What ``apply()`` actually did, for CLI reporting."""

    created: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)


def _is_meaningful(rel_path: str, content: str) -> bool:
    """False for whole-file-gated content that rendered empty.

    ``__init__.py`` is legitimately empty as a package marker (mirrors
    ``manual_updater._is_empty_stub``); every other path is "absent" once
    stripped to nothing.
    """
    if Path(rel_path).name == "__init__.py":
        return True
    return bool(content.strip())


class RenderDiffEngine:
    """Classifies and applies the answers-diff for one template tree.

    ``jinja_env`` must be configured with the same rendering semantics
    ``ManualUpdater`` and Copier use (``trim_blocks=False``,
    ``lstrip_blocks=False``, ``keep_trailing_newline=True``) or every
    regenerated file drifts from what init produced.
    """

    def __init__(
        self, jinja_env: Environment, template_root: Path, project_path: Path
    ) -> None:
        self.jinja_env = jinja_env
        self.template_root = template_root
        self.project_path = project_path
        # rel_path -> (policy, annotation-stripped source) for .jinja files,
        # or None for verbatim/absent paths. Neither depends on answers, so
        # this is read from disk at most once per path per engine instance.
        self._source_cache: dict[str, tuple[FilePolicy, str] | None] = {}

    def _jinja_source(self, rel_path: str) -> tuple[FilePolicy, str] | None:
        if rel_path not in self._source_cache:
            jinja_path = (
                self.template_root
                / PROJECT_SLUG_PLACEHOLDER
                / f"{rel_path}{JINJA_EXTENSION}"
            )
            if jinja_path.is_file():
                self._source_cache[rel_path] = _read_policy_and_body(
                    jinja_path.read_text()
                )
            else:
                self._source_cache[rel_path] = None
        return self._source_cache[rel_path]

    def policy_for(self, rel_path: str) -> FilePolicy:
        """The policy this path's template declares, or DEFAULT."""
        cached = self._jinja_source(rel_path)
        return cached[0] if cached is not None else FilePolicy.DEFAULT

    def _render(self, rel_path: str, answers: dict[str, Any]) -> str:
        """Render ``rel_path`` at ``answers``.

        Returns ``""`` when the template doesn't exist for this path, or
        when it renders to nothing meaningful (whole-file gate off) — both
        mean "this file is absent in this state" for classification.

        Reads the raw template source directly (rather than
        ``jinja_env.get_template``) so a leading policy annotation can be
        parsed and stripped before Jinja ever sees the text — Jinja's own
        comment-stripping isn't used here because its interaction with
        ``trim_blocks``/whitespace around the annotation line isn't
        something we want the render path depending on.
        """
        cached = self._jinja_source(rel_path)
        if cached is not None:
            content = self.jinja_env.from_string(cached[1]).render(answers)
        else:
            raw_path = self.template_root / PROJECT_SLUG_PLACEHOLDER / rel_path
            if not raw_path.is_file():
                return ""
            content = raw_path.read_text()
        return content if _is_meaningful(rel_path, content) else ""

    def discover_paths(self) -> list[str]:
        """Every project-relative path the template tree can produce.

        Whole-file gates control *content*, not filenames, so walking the
        template tree once (regardless of any particular answers) yields
        every path the project could ever have. Guarded by
        ``tests/core/test_shared_scope_completeness.py``, which asserts no
        stack-dependent file falls through this walk unhandled.

        Tooling-cache directories (a stray ``__pycache__`` from importing
        the template's raw ``.py`` files) and binary assets (images,
        fonts — never templated, and ``read_text()`` on them raises
        ``UnicodeDecodeError``) are skipped via the same rule
        ``get_component_files`` already uses, so the two walks agree on
        what counts as template content.
        """
        slug_dir = self.template_root / PROJECT_SLUG_PLACEHOLDER
        if not slug_dir.is_dir():
            return []
        paths: set[str] = set()
        for path in slug_dir.rglob("*"):
            if not path.is_file() or _is_skippable_template_file(path):
                continue
            rel = path.relative_to(slug_dir)
            if rel.name.endswith(JINJA_EXTENSION):
                rel = rel.with_name(rel.name[: -len(JINJA_EXTENSION)])
            paths.add(rel.as_posix())
        return sorted(paths)

    def _pristine(self, rel_path: str, disk_content: str, baseline: str) -> bool:
        """True if ``disk_content`` still matches the template's ``baseline``
        render, i.e. the project hasn't hand-edited this file.

        Whitespace-insensitive first; for ``.py`` files that still differ,
        re-compares after ruff-normalizing both sides so formatting drift
        (``make fix``) isn't mistaken for a user edit (issue #715; same
        discipline as the update path's ``_sync_python_file``).
        """
        if normalize_for_compare(disk_content) == normalize_for_compare(baseline):
            return True
        if not rel_path.endswith(".py"):
            return False
        disk_norm = run_ruff_on_text(disk_content, self.project_path, "", rel_path)
        base_norm = run_ruff_on_text(baseline, self.project_path, "", rel_path)
        if disk_norm is None or base_norm is None:
            return False
        return normalize_for_compare(disk_norm) == normalize_for_compare(base_norm)

    def _merge(
        self, rel_path: str, disk_content: str, base: str, ours: str
    ) -> str | None:
        """3-way merge: base = old render, theirs = disk, ours = new render.

        ``.py`` files are normalized through ``ruff check --fix --select I``
        first (import sorting only, never deletes code) so formatting noise
        can't manufacture a conflict — the #715 Phase B discipline, same
        as the update path's ``_sync_python_file``. If even one of the
        three normalizations fails, merging on a mix of normalized and raw
        content would reintroduce exactly the formatting noise the
        normalization exists to remove — bail to ``None`` (caller
        preserves) rather than merge on inconsistent inputs.

        Returns ``None`` when the merge could not run at all: ruff
        unavailable/failed on a ``.py`` file, or ``git merge-file`` itself
        unavailable/erroring (``merge_three_way_text`` returncode outside
        ``0..127``, in which case its ``merged`` text is `""` and must
        never be mistaken for a legitimate empty-file merge result).
        """
        theirs = disk_content
        if rel_path.endswith(".py"):
            theirs_n = run_ruff_on_text(theirs, self.project_path, "I", rel_path)
            base_n = run_ruff_on_text(base, self.project_path, "I", rel_path)
            ours_n = run_ruff_on_text(ours, self.project_path, "I", rel_path)
            if theirs_n is None or base_n is None or ours_n is None:
                return None
            theirs, base, ours = theirs_n, base_n, ours_n
        returncode, merged = merge_three_way_text(theirs, base, ours)
        if returncode < 0 or returncode > 127:
            return None
        return merged

    def _classify(
        self,
        rel_path: str,
        base: str,
        ours: str,
        project_file: Path,
        policy: FilePolicy,
    ) -> FilePlan:
        theirs_exists = project_file.exists()
        theirs = project_file.read_text() if theirs_exists else ""

        base_empty = base == ""
        ours_empty = ours == ""

        if base_empty and ours_empty:
            return FilePlan(rel_path, FileAction.SKIP, policy=policy)

        if base_empty and not ours_empty:
            # Component/file being added.
            if not theirs_exists:
                return FilePlan(rel_path, FileAction.CREATE, ours, policy=policy)
            if self._pristine(rel_path, theirs, base):
                # On disk but matching the empty BASE — an init-time stub
                # from a whole-file gate that was off (``{%- if -%}`` still
                # emits a newline). That IS what the template currently
                # produces, so it's pristine and safe to populate. Skipping
                # this check and comparing against OURS instead misreads
                # the stub as user content and preserves it, leaving the
                # file permanently empty — and for non-``.py`` files
                # nothing else cleans it up, since ``sweep_empty_stubs``
                # only sweeps ``*.py``. Reachable via ``aegis add ingress``
                # on a base project, which would otherwise never write
                # docker-compose.prod.yml / .env.deploy.example /
                # scripts/server-setup.sh.
                return FilePlan(rel_path, FileAction.OVERWRITE, ours, policy=policy)
            if normalize_for_compare(theirs) == normalize_for_compare(ours):
                return FilePlan(rel_path, FileAction.SKIP, policy=policy)
            # A file exists on disk despite no base render — no safe merge
            # base to reconcile against. Preserve rather than guess, same
            # precedent as sync_template_changes' "no merge base" handling
            # (issue #773).
            return FilePlan(rel_path, FileAction.PRESERVE, policy=policy)

        if not base_empty and ours_empty:
            # Component/file being removed.
            if not theirs_exists:
                return FilePlan(rel_path, FileAction.SKIP, policy=policy)
            if policy is FilePolicy.USER_OWNED:
                return FilePlan(rel_path, FileAction.PRESERVE, policy=policy)
            if self._pristine(rel_path, theirs, base):
                return FilePlan(rel_path, FileAction.DELETE, policy=policy)
            return FilePlan(rel_path, FileAction.PRESERVE, policy=policy)

        if normalize_for_compare(base) == normalize_for_compare(ours):
            # This operation doesn't change this file's content.
            if not theirs_exists:
                # Older project that predates this file at its current
                # (unchanged-by-this-op) configuration — backfill it.
                return FilePlan(rel_path, FileAction.CREATE, ours, policy=policy)
            return FilePlan(rel_path, FileAction.SKIP, policy=policy)

        # base and ours both present and differ — this operation touches
        # this file.
        if not theirs_exists:
            return FilePlan(rel_path, FileAction.CREATE, ours, policy=policy)
        if self._pristine(rel_path, theirs, base):
            return FilePlan(rel_path, FileAction.OVERWRITE, ours, policy=policy)
        if normalize_for_compare(theirs) == normalize_for_compare(ours):
            return FilePlan(rel_path, FileAction.SKIP, policy=policy)

        if policy in (FilePolicy.USER_OWNED, FilePolicy.WARN_IF_DIVERGED):
            return FilePlan(rel_path, FileAction.PRESERVE, policy=policy)

        merged = self._merge(rel_path, theirs, base, ours)
        if merged is None:
            # Merge machinery unavailable (git/ruff) — never guess; leave
            # the user's file exactly as it is.
            return FilePlan(rel_path, FileAction.PRESERVE, policy=policy)
        conflict = "<<<<<<<" in merged
        return FilePlan(
            rel_path, FileAction.MERGE, merged, conflict=conflict, policy=policy
        )

    def plan(
        self,
        old_answers: dict[str, Any],
        new_answers: dict[str, Any],
        *,
        paths: Iterable[str] | None = None,
    ) -> list[FilePlan]:
        """Classify files the template tree can produce.

        ``old_answers`` is the project's configuration *before* this
        operation, ``new_answers`` is what it will be after. For an add,
        that's ``self.answers`` vs ``self.answers | {include_x: True}``;
        for a removal, the reverse — callers must pass answers in that
        order or BASE/OURS invert and every classification flips.

        ``paths`` restricts classification to an explicit subset — every
        other discoverable path is neither rendered nor written, full
        stop. Defaults to :meth:`discover_paths` (the whole tree), correct
        only when nothing else claims ownership of any path in it. A
        caller managing component-owned files separately (``ManualUpdater``
        alongside ``FileManifest``, aegis-stack#918) must pass an explicit
        scope — otherwise the engine will "backfill create" a component's
        own files into a project that never selected that component, the
        first time it renders non-empty for reasons unrelated to that
        component's own gate.
        """
        return [
            self._classify(
                rel_path,
                self._render(rel_path, old_answers),
                self._render(rel_path, new_answers),
                self.project_path / rel_path,
                self.policy_for(rel_path),
            )
            for rel_path in (paths if paths is not None else self.discover_paths())
        ]

    def _write(self, output_path: Path, content: str, rel_path: str) -> None:
        """Write ``content``, ruff-formatted for ``.py`` files (mirrors
        ``ManualUpdater._write_rendered`` so engine output matches what init
        + ``make fix`` would have produced)."""
        if rel_path.endswith(".py"):
            formatted = run_ruff_on_text(content, self.project_path, "", rel_path)
            if formatted is not None:
                content = formatted
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    def apply(self, plans: list[FilePlan], *, backup: bool = True) -> RenderDiffResult:
        """Execute a plan produced by :meth:`plan` against the project tree."""
        result = RenderDiffResult()

        for p in plans:
            output_path = self.project_path / p.rel_path

            if p.action == FileAction.SKIP:
                continue

            if p.action == FileAction.PRESERVE:
                result.preserved.append(p.rel_path)
                continue

            if p.action == FileAction.DELETE:
                output_path.unlink(missing_ok=True)
                result.deleted.append(p.rel_path)
                continue

            if p.action == FileAction.CREATE:
                assert p.content is not None
                self._write(output_path, p.content, p.rel_path)
                result.created.append(p.rel_path)
                continue

            if p.action == FileAction.OVERWRITE:
                assert p.content is not None
                if (
                    backup
                    and p.policy is not FilePolicy.NO_BACKUP
                    and output_path.exists()
                ):
                    backup_path = output_path.with_suffix(
                        output_path.suffix + ".backup"
                    )
                    shutil.copy(output_path, backup_path)
                    result.backed_up.append(p.rel_path)
                self._write(output_path, p.content, p.rel_path)
                result.overwritten.append(p.rel_path)
                continue

            if p.action == FileAction.MERGE:
                assert p.content is not None
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(p.content)
                if p.conflict:
                    result.conflicts.append(p.rel_path)
                else:
                    result.merged.append(p.rel_path)
                continue

        return result
