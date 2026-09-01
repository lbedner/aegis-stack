"""Display helpers for the composer's model selector (pure, testable).

The selector itself lives in ``model_picker``; these shape API payloads
(``/api/v1/llm/current``, ``/api/v1/llm/models``) into what it renders.
"""

from typing import Any

# The composer chip is inline with the input; longer ids clip.
_CHIP_LABEL_LIMIT = 24


def model_label(current: dict[str, Any] | None, limit: int = _CHIP_LABEL_LIMIT) -> str:
    """The composer chip's text: the resolved model id, clipped."""
    name = str((current or {}).get("model") or "")
    if not name:
        return "model"
    return name if len(name) <= limit else name[: limit - 3] + "..."


def newest_first(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Release date descending; undated models sink to the bottom."""
    return sorted(
        models,
        key=lambda m: (
            m.get("released_on") is not None,
            m.get("released_on") or "",
        ),
        reverse=True,
    )


def family_display_name(family: str | None) -> str:
    """A catalog family slug as a group title: ``claude-3.5`` -> ``Claude 3.5``."""
    if not family:
        return "Other"
    words = family.replace("-", " ").replace("_", " ").split()
    # Capitalize first letters only; str.title() would turn "4o" into "4O".
    return " ".join(word[:1].upper() + word[1:] for word in words)


def group_models(
    models: list[dict[str, Any]], by: str = "vendor"
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Catalog rows grouped for the picker, newest models first per group.

    ``by="vendor"`` keys on vendor name; ``by="family"`` on the prettified
    family slug. Unknown values land in "Other", which always sorts last.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for model in models:
        if by == "family":
            key = family_display_name(model.get("family"))
        else:
            key = model.get("vendor") or "Other"
        groups.setdefault(key, []).append(model)
    ordered = sorted(groups, key=lambda name: (name == "Other", name))
    return [(name, newest_first(groups[name])) for name in ordered]


def format_context_window(tokens: int | None) -> str:
    """A context window as the compact figure people say: 128k, 1M."""
    if not tokens:
        return ""
    if tokens >= 1_000_000:
        millions = tokens / 1_000_000
        return f"{millions:.0f}M" if millions >= 1.05 or millions < 1.0 else "1M"
    return f"{round(tokens / 1_000)}k"


def _usd(value: float) -> str:
    """$3, $1.25 - cents only when they carry information."""
    return f"${value:g}" if value == int(value) else f"${value:.2f}"


def format_price(input_price: float | None, output_price: float | None) -> str:
    """Per-million-token pricing as ``$in / $out``; blanks stay blank."""
    if input_price is None and output_price is None:
        return ""
    if output_price is None:
        return _usd(input_price or 0.0)
    if input_price is None:
        return _usd(output_price)
    return f"{_usd(input_price)} / {_usd(output_price)}"


def filter_models(models: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Case-insensitive substring match over id, title, and vendor."""
    needle = query.strip().casefold()
    if not needle:
        return models
    return [
        m
        for m in models
        if needle
        in f"{m.get('model_id', '')} {m.get('title', '')} {m.get('vendor', '')}".casefold()
    ]


def display_title(model: dict[str, Any], *, under_vendor: str | None = None) -> str:
    """The row title: under a vendor's own section, the catalog's baked
    "Vendor: " prefix is the header said twice, so it comes off; flat
    views (All, search) keep it - there it IS the context."""
    title = str(model.get("title") or model.get("model_id") or "")
    vendor = str(model.get("vendor") or "")
    if (
        under_vendor
        and vendor
        and title.casefold().startswith(f"{vendor}: ".casefold())
    ):
        return title[len(vendor) + 2 :]
    return title


def lab_for_model(model: dict[str, Any]) -> str | None:
    """Who MADE a model, as the catalog resolved it at sync time.

    This used to be inferred from the model id against a table of
    product-line prefixes, which is wrong twice over: labs ship under
    new names (Meta's Muse Glimmer carries no "llama" anywhere), and a
    local rename would have reassigned the model to a stranger. The
    catalog now stores the publishing org on the row (``made_by_org_id``
    into ``llm_org``), so this is a read, and a model the registry does
    not know stays honestly unmarked.
    """
    lab = model.get("lab")
    return str(lab) if lab else None
