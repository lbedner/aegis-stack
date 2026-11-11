"""
Declarative file manifest per ``PluginSpec``.

R1 of the plugin system refactor. Centralises the per-spec file
ownership needed for declarative cleanup, replacing the **Pattern A**
imperative blocks ("if X is not selected, remove these files") that
were scattered through ``aegis/core/post_gen_tasks.py``.

Consumed by every ``PluginSpec`` (in-tree services and components today;
third-party plugins under R2+). See ``aegis/core/plugin_spec.py``.

``post_gen_tasks.get_component_file_mapping()`` is now derived from these
manifests via ``compute_file_mapping()`` below — there is no longer a
hand-maintained mapping dict to drift against. ``mapping[name]`` is each
spec's ``primary`` add base; every ``extras`` group is emitted under its own
key for the option/variant-gated consumers.

What R1 does NOT do (deliberately deferred to R2):

* Sub-feature, cross-spec, and worker-backend cleanups remain inline in
  ``cleanup_components`` (their gating predicates are non-uniform).

Everything else stays inline in ``cleanup_components`` for R1:

* Pattern B sub-feature cleanup (``ai_rag``, oauth, the langchain strip).
  ``auth_org``, ``ai_voice``, ``ai_evals`` and both persistence groups have
  since moved to their spec's ``extras``.
* Pattern C cross-spec aggregations (``alembic`` only when no service
  needs migrations; ``services_card.py`` only when no services;
  ``docs/components`` only when no components).
* Pattern D worker backend-variant rename + delete-others.

The ``extras`` field on ``FileManifest`` holds the gated groups; init,
add and remove read them through ``component_files.group_on``.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FileManifest:
    """File ownership for a single service or component spec.

    See module docstring for the role this plays in R1.
    """

    primary: list[str] = field(default_factory=list)
    """Files cleaned up when the parent spec is not selected.

    Paths are relative to the project root. Each entry may be a file path
    or a directory path; directories are removed recursively.
    """

    extras: dict[str, list[str]] = field(default_factory=dict)
    """Option/variant-gated file groups, keyed by their mapping identifier.

    These files render empty unless their option is enabled (``ai_rag``,
    ``ai_voice``) or only exist for a specific backend
    (``scheduler_persistence``), so they are kept out of the always-on
    ``primary`` add base, and folded into the full footprint by
    ``get_component_files(..., full=True)`` for ``aegis remove``. Init's
    ``cleanup_components`` removes a selected spec's group when its gate
    (``component_files.group_on``) is off.

    Example: ``{"ai_rag": [...], "ai_voice": [...]}`` on the AI service.
    """


def compute_file_mapping(specs: Iterable[Any]) -> dict[str, list[str]]:
    """Build the component-file mapping from spec manifests.

    This is the single source for ``get_component_file_mapping()``. Output
    shape: ``{spec_name: primary, ...}``. A spec's ``extras`` are read off the
    spec itself, through ``component_files.group_on``.

    Specs without a populated ``FileManifest`` are skipped — CORE components
    (backend/frontend) and any non-migrated spec do not break the reducer.
    """
    mapping: dict[str, list[str]] = {}
    for spec in specs:
        manifest = getattr(spec, "files", None)
        if not isinstance(manifest, FileManifest):
            continue
        if manifest.primary:
            mapping[spec.name] = list(manifest.primary)
    return mapping


def iter_cleanup_paths(spec: Any, *, selected: bool) -> Iterable[str]:
    """Yield project-relative paths to remove for one spec when it is off.

    When ``selected`` is True, yields nothing (sub-feature cleanup is
    handled inline). When False, yields the spec's complete footprint —
    ``primary`` plus every ``extras`` group — matching
    ``get_component_cleanup_paths``: a spec that is off owns none of its
    files, gated or not. Extras matter here because option-gated files
    that are NOT empty-rendering (e.g. auth's htmx login pages, plain
    HTML) would otherwise survive an init that never selected the spec
    (issue #814).

    Args:
        spec: A spec object exposing ``.files: FileManifest``. Specs
            without a manifest yield nothing.
        selected: Whether this spec is selected (its ``include_*`` flag
            is truthy in the context).

    Yields:
        Relative paths to remove (file or directory; caller decides how).
    """
    if selected:
        return
    manifest = getattr(spec, "files", None)
    if not isinstance(manifest, FileManifest):
        return
    yield from manifest.primary
    for extra_files in (manifest.extras or {}).values():
        yield from extra_files


def apply_cleanup_path(project_path: Path, rel_path: str) -> None:
    """Remove a single project-relative path. File or directory; no-op if absent.

    Mirrors the union of ``post_gen_tasks.remove_file`` and
    ``post_gen_tasks.remove_dir`` so callers don't need to know the kind.
    """
    full = project_path / rel_path
    if full.is_file() or full.is_symlink():
        full.unlink()
    elif full.is_dir():
        shutil.rmtree(full)
    # else: missing -> silent no-op, matches existing behaviour.
