"""Every column either table in this modal has, and how wide it is.

The widths are here rather than next to their tables because
``MODEL_TABLE_WIDTH`` is their sum and the modal sizes itself from it:
change a width and the modal follows, instead of drifting from the
table it is meant to contain.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.components.frontend.controls.data_table import (
    PICKER_GUTTER_WIDTH,
    DataTableColumn,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_constants import ModalLayout

# Model table column widths
COL_WIDTH_MODEL_NAME = 170


COL_WIDTH_ID = 100


COL_WIDTH_PARAMS = 56


COL_WIDTH_QUANT = 50


COL_WIDTH_CONTEXT = 60


# Wide enough for the longest header ("Thinking") plus its sort chevron.
COL_WIDTH_CAPABILITY = 74


COL_WIDTH_SIZE = 58


# Holds "11 minutes ago" on one line.
COL_WIDTH_MODIFIED = 116


COL_WIDTH_VRAM = 56


COL_WIDTH_STATUS = 78


COL_WIDTH_ACTIVE = 66


@dataclass(frozen=True)
class Capability:
    """One Ollama capability flag, and the column that reports it.

    ``key`` is the string Ollama puts in ``capabilities``. Driving both
    the column list and the row cells off this one table is what stops a
    capability from ending up with a column and no cell, or the reverse.
    """

    key: str
    header: str
    visible: bool = True


# ``completion`` is deliberately absent: every generative model carries
# it, so a column of "Yes" costs real width and separates nothing.
# ``tools`` leads because it gates agent use at all - a model that cannot
# call a tool cannot drive an agent, whatever its prose is like.
# ``embedding`` ships hidden: no chat model has it, but a pulled
# embedding model would, and a hidden column costs no width.
CAPABILITIES = [
    Capability("tools", "Tools"),
    Capability("vision", "Vision"),
    Capability("thinking", "Thinking"),
    Capability("insert", "Insert"),
    Capability("embedding", "Embed", visible=False),
]


# Model table columns for DataTable.
#
# Ordered to read as a sentence: what it is (Model, ID), how big it is
# (Params, Quant, Context, Size), what it can do (one column per
# capability), when it arrived (Modified), and what it is doing right now
# (VRAM, Status, Active).
MODEL_COLUMNS = [
    DataTableColumn("Model", width=COL_WIDTH_MODEL_NAME, style="body", hideable=False),
    DataTableColumn("ID", width=COL_WIDTH_ID, style="secondary"),
    DataTableColumn("Params", width=COL_WIDTH_PARAMS, style="secondary"),
    DataTableColumn("Quant", width=COL_WIDTH_QUANT, style="secondary"),
    DataTableColumn(
        "Context", width=COL_WIDTH_CONTEXT, alignment="right", style="secondary"
    ),
    *(
        DataTableColumn(
            cap.header,
            width=COL_WIDTH_CAPABILITY,
            style="secondary",
            visible=cap.visible,
        )
        for cap in CAPABILITIES
    ),
    DataTableColumn("Size", width=COL_WIDTH_SIZE, alignment="right", style="secondary"),
    DataTableColumn("Modified", width=COL_WIDTH_MODIFIED, style="secondary"),
    DataTableColumn("VRAM", width=COL_WIDTH_VRAM, alignment="right", style="secondary"),
    DataTableColumn("Status", width=COL_WIDTH_STATUS, sortable=False),
    DataTableColumn("Active", width=COL_WIDTH_ACTIVE, sortable=False),
]


def table_width(columns: list[DataTableColumn]) -> int:
    """What the DataTable actually occupies, chrome included.

    Columns and the gutters between them are the obvious part. The two
    that got missed on the first cut, and pushed the last column out past
    the table's own right border: the table spends ``Spacing.MD`` of
    padding on EACH side of every row, and the column-picker button takes
    a whole trailing gutter that is not a column.

    Hidden-by-default columns are excluded - they are one picker click
    away and must not widen the modal for anyone who never clicks.
    """
    shown = [c for c in columns if c.visible]
    return (
        sum(c.width or 0 for c in shown)
        + Theme.Spacing.MD * (len(shown) - 1)
        + Theme.Spacing.MD * 2
        + PICKER_GUTTER_WIDTH
        + Theme.Spacing.MD
    )


# Every column is fixed-width, so the table's own width is knowable and
# the modal can be sized to hold it. A column left to flex among fixed
# siblings renders at ZERO width once the row overflows rather than
# wrapping - invisible to a control-tree test, so the arithmetic is the
# guard (see test_ollama_model_table.py).
MODEL_TABLE_WIDTH = table_width(MODEL_COLUMNS)


# What the dialog must be opened at to hold that table: the section and
# tab padding either side, plus the dialog's own content padding, which
# is spent INSIDE the declared width rather than around it.
MODELS_MODAL_WIDTH = (
    MODEL_TABLE_WIDTH
    + Theme.Spacing.MD * 2
    + Theme.Spacing.SM * 2
    + ModalLayout.CONTENT_PADDING * 2
)


# Activity table columns for DataTable
ACTIVITY_COLUMNS = [
    DataTableColumn("Model", width=COL_WIDTH_MODEL_NAME, style="body"),
    DataTableColumn("Event", width=90),
    DataTableColumn("VRAM", width=COL_WIDTH_VRAM, alignment="right", style="secondary"),
    DataTableColumn("Source", width=80, style="secondary"),
    DataTableColumn("When", width=140, style="secondary"),
]
