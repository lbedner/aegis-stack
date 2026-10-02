"""queryspy baseline entries keyed on a statement's shape, not its text.

queryspy names a repeated statement by its whole SQL, so adding a column to
a table renames every SELECT on it, and the baseline then reads as all new.
The shape drops the selected-column list: a new column keeps an entry, while
a new WHERE, a new join, ``DISTINCT``, or a call site in another function
still makes a new one. queryspy's identity leaves out line numbers, so the
same statement at another line of one function was never a new entry. The
label stays readable SQL, so a baseline diff still says what changed.

ponytail: rides two queryspy internals, ``_baseline.entry_for`` and the
plugin's baseline stash, pinned by ``queryspy<0.5`` and guarded by
``tests/test_queryspy_shape.py``. Delete this module once queryspy keys
statements this way itself.
"""

from __future__ import annotations

import dataclasses
import re

import pytest
from queryspy import _baseline, pytest_plugin
from queryspy._baseline import BaselineEntry
from queryspy._detect import Finding

# Everything between the first SELECT and its FROM: the selected columns,
# with DISTINCT kept, since it changes what the statement returns.
_SELECT_LIST = re.compile(r"^SELECT\b(?P<distinct> DISTINCT\b)?.*?\bFROM\b", re.DOTALL)


def statement_shape(sql: str) -> str:
    """The statement with its selected columns collapsed to ``...``."""
    return _SELECT_LIST.sub(
        lambda match: f"SELECT{match['distinct'] or ''} ... FROM",
        " ".join(sql.split()),
        count=1,
    )


def shaped(entry: BaselineEntry) -> BaselineEntry:
    """The entry with a statement label reduced to its shape."""
    if entry.kind != "repeated_statement":
        return entry
    return dataclasses.replace(entry, label=statement_shape(entry.label))


_entry_for_text = _baseline.entry_for


def entry_for(finding: Finding, *, root: str | None = None) -> BaselineEntry:
    """queryspy's identity for a finding, by shape. Every comparison it
    makes (split, stale, save) builds entries through this name."""
    return shaped(_entry_for_text(finding, root=root))


_baseline.entry_for = entry_for


def shape_loaded_baseline(config: pytest.Config) -> None:
    """Reshape the baseline queryspy read at configure time, so a file
    written before shapes, or by hand, still matches."""
    key = pytest_plugin._BASELINE
    if key in config.stash:
        config.stash[key] = {shaped(entry) for entry in config.stash[key]}
