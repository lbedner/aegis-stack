"""What goes in one cell of the models table.

Six formatters, each the rule for one column: a quantization that
Ollama reports inconsistently, an id too long to show whole, a context
length in tokens, a capability as a tag, a modified date as elapsed
time. They are separate from the table because each is a rule worth
asserting on its own, and the generated model-table tests do.
"""

from __future__ import annotations

import flet as ft
from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.data_table import (
    CELL_ELLIPSIS_KWARGS,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time as format_relative_iso

# Digest characters shown, matching `ollama list`.
MODEL_ID_LENGTH = 12


def format_quantization(quant: str) -> str:
    """Convert quantization level to human-readable format.

    Q4_K_M → 4-bit
    Q8_0 → 8-bit
    Q5_K_S → 5-bit
    """
    if not quant or quant == "—":
        return "—"
    # Extract the bit number from formats like Q4_K_M, Q8_0, Q5_K_S
    if quant.startswith("Q") and len(quant) > 1:
        bit_num = quant[1]
        if bit_num.isdigit():
            return f"{bit_num}-bit"
    return quant


def model_cell(text: str, *, numeric: bool = False) -> ft.Text:
    """One Models-table cell, styled the way ``style_cell`` styles a
    plain value.

    This table passes BUILT controls (it needs per-cell colours and a
    sort key on Modified), which means ``style_cell`` hands them straight
    through and applies none of its treatment. Reapplying it here is what
    keeps this table looking like every other one: BODY size, and single
    line with an ellipsis rather than wrapping into a second row.

    ``numeric`` picks the tabular face so right-aligned figures line up.
    """
    cls = NumericText if numeric else SecondaryText
    return cls(
        text,
        size=Theme.Typography.BODY,
        color=Theme.Colors.TEXT_SECONDARY,
        **CELL_ELLIPSIS_KWARGS,
    )


def format_model_id(digest: str) -> str:
    """Short digest, the same 12 characters ``ollama list`` prints.

    The full sha256 is 64 characters and would dominate the row; the
    leading 12 are what Ollama itself considers enough to identify a
    build, and they are what the user sees in the terminal.
    """
    if not digest:
        return "—"
    return digest[:MODEL_ID_LENGTH]


def format_context_length(tokens: int) -> str:
    """Context window in K, because 262144 is a number you have to stop
    and divide before it means anything.

    Keeps one decimal only when rounding would lie (1536 -> 1.5K, not
    2K); stays in raw tokens below 1K.
    """
    if tokens <= 0:
        return "—"
    if tokens < 1024:
        return str(tokens)
    k = tokens / 1024
    return f"{k:.0f}K" if abs(k - round(k)) < 0.05 else f"{k:.1f}K"


def capability_cell(present: bool) -> ft.Text:
    """One capability column's cell: plain "Yes" or "No".

    Plain words rather than an icon or a dash, because sorting is what
    stands in for filtering here and it only groups cleanly when the two
    values are stable text. A blank for absent would also be ambiguous -
    it would read as "Ollama did not say" rather than "no".

    Monochrome-first: the present one takes primary ink and the absent
    one recedes, instead of spending a hue on a boolean.
    """
    return SecondaryText(
        "Yes" if present else "No",
        size=Theme.Typography.BODY,
        color=Theme.Colors.TEXT_PRIMARY if present else Theme.Colors.TEXT_SECONDARY,
        **CELL_ELLIPSIS_KWARGS,
    )


def build_modified_cell(modified_at: str) -> SecondaryText:
    """When this model was pulled, shown relatively and sorted absolutely.

    Displays "6 months ago" (what ``ollama list`` shows) but stamps the
    ISO timestamp into ``.data``, which ``DataTable`` reads ahead of the
    display text precisely so a humanized date still sorts by real time
    rather than alphabetically.
    """
    cell = model_cell(format_relative_iso(modified_at, coarse=True))
    cell.data = modified_at
    return cell
