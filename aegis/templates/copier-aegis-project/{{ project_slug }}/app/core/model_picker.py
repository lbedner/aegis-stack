"""Display helpers for a model picker (pure, testable).

Shared by every surface that lets a person pick the active model (the web
chat's picker, the Flet panel's): these shape the catalog payloads
(``/api/v1/llm/current``, ``/api/v1/llm/models``) into what it renders.
"""

import re
from typing import Any

# A dated snapshot's id: its base model's, and the date it was cut.
_DATED = re.compile(r"-\d{4}-?\d{2}-?\d{2}$")

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


def base_model(model_id: str) -> str:
    """A model's id without a dated snapshot's date:
    ``gpt-realtime-mini-2025-12-15`` is a version of ``gpt-realtime-mini``."""
    return _DATED.sub("", model_id)


def one_per_base(
    models: list[dict[str, Any]], keep: str | None = None
) -> list[dict[str, Any]]:
    """``models`` with a base model's dated versions folded into one row,
    where the first of them stood, its ``versions`` how many it holds. The
    row is ``keep``'s where it is one of them (the one in use), else the
    base's own id (which follows the newest), else the first."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in models:
        groups.setdefault(base_model(m["model_id"]), []).append(m)
    folded = []
    for base, versions in groups.items():
        ids = {m["model_id"]: m for m in versions}
        lead = ids.get(keep or "") or ids.get(base) or versions[0]
        folded.append({**lead, "versions": len(versions)})
    return folded


def family_display_name(family: str | None) -> str:
    """A catalog family slug as a group title: ``claude-3.5`` -> ``Claude 3.5``."""
    if not family:
        return "Other"
    words = family.replace("-", " ").replace("_", " ").split()
    # Capitalize first letters only; str.title() would turn "4o" into "4O".
    return " ".join(word[:1].upper() + word[1:] for word in words)


def group_models(
    models: list[dict[str, Any]], by: str = "vendor", keep: str | None = None
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Catalog rows grouped for the picker, newest models first per group,
    a model's dated versions one row (``one_per_base``, ``keep`` the one in
    use).

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
    return [(name, one_per_base(newest_first(groups[name]), keep)) for name in ordered]


def format_context_window(tokens: int | None) -> str:
    """A context window as the compact figure people say: 128k, 1M.

    Whichever thousand divides it exactly: a hosted catalog's 128000 by
    1000, Ollama's 131072 by 1024 (128k, not 131k). One decimal stays only
    when rounding would lie (1.5k, not 2k).
    """
    if not tokens:
        return ""
    if tokens >= 1_000_000:
        millions = tokens / 1_000_000
        return f"{millions:.0f}M" if millions >= 1.05 or millions < 1.0 else "1M"
    if tokens < 1_000:
        return str(tokens)
    k = tokens / (1024 if tokens % 1000 and not tokens % 1024 else 1000)
    return f"{k:.0f}k" if abs(k - round(k)) < 0.05 else f"{k:.1f}k"


def _usd(value: float) -> str:
    """$3, $1.25 - cents only when they carry information."""
    return f"${value:g}" if value == int(value) else f"${value:.2f}"


def format_per_minute(usd: float) -> str:
    """A rate by the minute: "$0.02 a minute", tenths of a cent shown
    where cents would round it away."""
    shown = _usd(usd) if usd >= 0.01 else f"${usd:.3f}"
    return f"{shown} a minute"


def is_local_model(model: dict[str, Any]) -> bool:
    """Does this model run on this machine. Reads either spelling: a catalog
    row calls it ``vendor``, a finished message's metadata ``provider``.
    The local vendors are the local providers (Ollama, llama.cpp); read
    here, not imported above, because the pickers' formatters serve the
    inference pages without the AI service."""
    from app.core.discovery import optional

    # A stack without the AI service (the Flet picker ships in every one)
    # runs nothing locally.
    local = optional("app.services.ai.service", "LOCAL_PROVIDERS") or ()
    named = model.get("vendor") or model.get("provider") or ""
    return str(named).casefold() in local


UNKNOWN_PRICE = "Price unknown"


def format_price(
    input_price: float | None, output_price: float | None, *, local: bool = False
) -> str:
    """Per-million-token pricing as ``$in / $out``. A cloud model with no
    pricing on file, or only zeros (a catalog's placeholder), is said to be
    unknown: blank or "$0 / $0" would read as free. A local model's nothing
    is the answer, so it says Free."""
    if not input_price and not output_price:
        return "Free" if local else UNKNOWN_PRICE
    if output_price is None:
        return _usd(input_price or 0.0)
    if input_price is None:
        return _usd(output_price)
    return f"{_usd(input_price)} / {_usd(output_price)}"


def model_price(model: dict[str, Any]) -> str:
    """What a model costs as a picker row says it: by the minute where it
    bills by time (``per_second``), else per million tokens in and out."""
    if per_second := model.get("per_second"):
        return format_per_minute(per_second * 60)
    return format_price(
        model.get("input_price"),
        model.get("output_price"),
        local=is_local_model(model),
    )


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
