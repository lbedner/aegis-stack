"""
Plugin scaffold renderer (#774).

Generates a new ``aegis-stack-<name>`` project from the templates
under ``aegis/templates/plugin_scaffold/``. The output is a
self-contained, pip-installable Python package that registers itself
via the ``aegis.plugins`` entry point — running
``pip install -e <generated-dir>`` and ``aegis plugins list`` shows
the new plugin immediately.

Path-name placeholders rendered at scaffold time:

* ``__PLUGIN_PKG__`` → ``aegis_stack_<name>`` (the Python package
  directory under ``src/``).
* ``__PROJECT_SLUG__`` → ``{{ project_slug }}`` (literal directory
  name in the plugin's ``templates/`` tree — matches the convention
  ``plugin_template_resolver`` walks at install time).
* ``__PLUGIN_NAME__`` → ``<name>`` (per-service folder under the
  project's ``app/services/`` tree).

File contents are rendered through Jinja2; only ``*.jinja`` files are
processed, and the ``.jinja`` suffix is stripped from the output path.
The current scaffold expects templated inputs only — non-jinja files
in the scaffold tree would be ignored, not copied. If a future scaffold
needs to ship verbatim assets, the rglob filter will need to broaden.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ... import __version__
from .naming import dist_name, package_name

JINJA_EXTENSION = ".jinja"
PLUGIN_PKG_PLACEHOLDER = "__PLUGIN_PKG__"
PROJECT_SLUG_PLACEHOLDER = "__PROJECT_SLUG__"
PLUGIN_NAME_PLACEHOLDER = "__PLUGIN_NAME__"

# Plugin name validation: a top-level Python package name (so it's
# importable as ``aegis_stack_<name>``). Lowercase letters, digits,
# and underscores; must start with a letter. No hyphens — Python doesn't
# accept those in module names.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _scaffold_template_root() -> Path:
    """Path to the scaffold templates shipped with the CLI.

    Three ``parent`` walks up from ``aegis/core/plugins/scaffold.py``
    land on the ``aegis/`` package root, then under ``templates/``.
    """
    return Path(__file__).parent.parent.parent / "templates" / "plugin_scaffold"


def validate_plugin_name(name: str) -> None:
    """Raise ``ValueError`` if ``name`` is not a valid Python identifier
    suitable for the ``aegis_stack_<name>`` package layout."""
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Plugin name {name!r} must be lowercase letters/digits/underscores "
            "and start with a letter (no hyphens, no spaces). "
            "Examples: 'scraper', 'metrics_hub', 'stripe'."
        )


def scaffold_plugin(
    name: str,
    target_dir: Path,
    *,
    author: str = "Plugin Author",
    description: str = "",
) -> list[Path]:
    """Render the plugin scaffold into ``target_dir / aegis-stack-<name>``.

    Args:
        name: Plugin name (will become the Python package
            ``aegis_stack_<name>``). Must validate against
            :func:`validate_plugin_name`.
        target_dir: Parent directory the scaffold lands inside. Must
            already exist.
        author: Free-form author string for ``pyproject.toml`` and the
            README.
        description: One-line description. Defaults to a generic
            placeholder.

    Returns:
        List of files created (absolute paths), in order of writing.

    Raises:
        ValueError: if ``name`` is invalid.
        FileExistsError: if ``target_dir / aegis-stack-<name>``
            already exists. Existing scaffolds are never overwritten;
            the caller (the CLI) chooses how to surface that.
        FileNotFoundError: if ``target_dir`` does not exist.
    """
    validate_plugin_name(name)
    if not target_dir.is_dir():
        raise FileNotFoundError(f"target_dir {target_dir} does not exist")

    output_root = target_dir / dist_name(name)
    if output_root.exists():
        raise FileExistsError(f"{output_root} already exists")

    template_root = _scaffold_template_root()
    description = description or f"Aegis Stack plugin: {name}"
    context = {
        "name": name,
        "author": author or "Plugin Author",
        "dist": dist_name(name),
        "pkg": package_name(name),
        "description": description,
        # The plugin is written against this aegis-stack's spec surface,
        # so the scaffold pins it as the floor rather than letting a
        # resolver pick an older one that lacks a field the plugin sets.
        "aegis_version": __version__,
    }

    # Single Jinja2 environment rooted at the scaffold templates.
    # ``keep_trailing_newline=True`` matches the source files so we
    # don't strip the final newline on rendered output (otherwise
    # ruff/pre-commit would flag every generated file as missing one).
    env = Environment(
        loader=FileSystemLoader(str(template_root)),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )

    written: list[Path] = []
    for source_file in sorted(template_root.rglob(f"*{JINJA_EXTENSION}")):
        rel = source_file.relative_to(template_root)
        # Strip the ``.jinja`` suffix from the output path.
        out_rel = rel.with_suffix("")

        # Substitute path-name placeholders. We do this on the string
        # form so it covers both directory and file segments uniformly,
        # then re-build a Path. If we Pathified each segment first we'd
        # have to handle the empty-suffix-after-strip case too — string
        # replace keeps it simple.
        out_str = str(out_rel)
        out_str = out_str.replace(PLUGIN_PKG_PLACEHOLDER, package_name(name))
        out_str = out_str.replace(PROJECT_SLUG_PLACEHOLDER, "{{ project_slug }}")
        out_str = out_str.replace(PLUGIN_NAME_PLACEHOLDER, name)
        out_path = output_root / out_str

        # Render through Jinja2 (template name is the relative path with
        # the ``.jinja`` suffix still on it — Jinja2's loader keys on
        # whatever string we pass).
        template = env.get_template(str(rel))
        content = template.render(**context)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content)
        written.append(out_path)

    return written
