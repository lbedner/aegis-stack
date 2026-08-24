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
