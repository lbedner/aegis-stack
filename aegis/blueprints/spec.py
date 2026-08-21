"""Blueprint spec: the data shape and the engine adapter.

A blueprint is nothing but a set of answers to the questions the shared
selection engine (:func:`aegis.cli.interactive.run_project_selection`) already
asks. It never builds component or service lists itself — every consumer runs
the real engine, so bracket syntax, auto-adds, and dependency rules stay in
one place:

- ``--blueprint <slug> --no-interactive`` runs the engine headlessly via
  :func:`blueprint_selection`.
- The guided setup runs the engine with the blueprint answering EVERY
  screen silently (journaled like keypresses), so the seeded pass lands
  straight on REVIEW; esc from the review pops answers and re-asks them
  live, and forward replay re-seeds from the blueprint again.

A blueprint is a starting point, not a cage: anything it leaves out is added
later with ``aegis add`` / ``aegis add-service``.

Individual blueprints live one-per-module in this package and are discovered
by :mod:`aegis.blueprints`; adding a preset means adding a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..cli.interactive import ProjectSelection, run_project_selection

# qkey prefix for yes/no acceptance screens; the suffix is the spec name.
ACCEPT_PREFIX = "accept:"


class QKeys:
    """The question keys a blueprint may answer.

    The contract between the guided screens (which ask under these keys)
    and blueprints (which answer them). It exists because an unrecognized
    key is INVISIBLE at runtime: ``pick_index`` falls back to the screen's
    default and ``pick_multi`` to its preselection, so a typo would ship a
    blueprint that quietly built a different stack. ``Blueprint`` rejects
    unknown keys, and a test holds this list and the screens in step.
    """

    WORKER_BACKEND = "worker_backend"
    SCHEDULER_BACKEND = "scheduler_backend"
    DATABASE_ENGINE = "database_engine"
    POSTGRES_PROVIDER = "postgres_provider"
    AUTH_LEVEL = "auth_level"
    AI_FRAMEWORK = "ai_framework"
    AI_STORAGE = "ai_storage"
    AI_PROVIDERS = "ai_providers"
    AI_RAG = "ai_rag"
    AI_VOICE = "ai_voice"

    ALL = (
        WORKER_BACKEND,
        SCHEDULER_BACKEND,
        DATABASE_ENGINE,
        POSTGRES_PROVIDER,
        AUTH_LEVEL,
        AI_FRAMEWORK,
        AI_STORAGE,
        AI_PROVIDERS,
        AI_RAG,
        AI_VOICE,
    )


@dataclass(frozen=True)
class Blueprint:
    """A named, described preset of selection-engine answers."""

    slug: str
    title: str
    description: str
    # Base names accepted at their confirm screens; everything else declines.
    components: tuple[str, ...]
    services: tuple[str, ...]
    # qkey -> value (single-select) or values (multi-select) for the
    # non-confirm screens. Missing keys fall back to the screen's default.
    # Free-form on purpose: a blueprint only states what it has an opinion
    # about, so new questions need no change here.
    answers: dict[str, str | tuple[str, ...]] = field(default_factory=dict)
    # Grouping label for the gallery once the roster warrants sections.
    category: str = ""

    def __post_init__(self) -> None:
        unknown = sorted(set(self.answers) - set(QKeys.ALL))
        if unknown:
            raise ValueError(
                f"Blueprint {self.slug!r} has unknown answer key(s): "
                f"{', '.join(unknown)}. Valid keys: {', '.join(QKeys.ALL)}"
            )

    def wants(self, name: str) -> bool:
        """Whether the confirm screen for ``name`` should be accepted."""
        return name in self.components or name in self.services

    @property
    def contents(self) -> tuple[str, ...]:
        """Declared components and services, base names, in stated order.

        What the gallery shows on an unfocused row. Engine auto-adds (redis
        behind worker) are deliberately absent: this is what the blueprint
        asks for, not the resolved plan.
        """
        return tuple(
            name.split("[", 1)[0] for name in (*self.components, *self.services)
        )


def pick_index(
    blueprint: Blueprint, qkey: str, values: list[str], default_idx: int
) -> int:
    """The blueprint's answer to a single-select screen, as a choice index.

    Acceptance screens (``accept:<name>``) answer by membership; keyed
    screens answer by value lookup; anything unknown takes the screen's
    default, so blueprints only need opinions where they differ from it.
    """
    if qkey.startswith(ACCEPT_PREFIX):
        want = "yes" if blueprint.wants(qkey.removeprefix(ACCEPT_PREFIX)) else "no"
        return values.index(want) if want in values else default_idx
    wanted = blueprint.answers.get(qkey)
    if isinstance(wanted, str) and wanted in values:
        return values.index(wanted)
    return default_idx


def pick_multi(
    blueprint: Blueprint, qkey: str, values: list[str], preselected: set[int]
) -> set[int]:
    """The blueprint's answer to a multi-select screen, as choice indices."""
    wanted = blueprint.answers.get(qkey)
    if wanted is None:
        return set(preselected)
    wanted_set = {wanted} if isinstance(wanted, str) else set(wanted)
    picked = {i for i, value in enumerate(values) if value in wanted_set}
    return picked or set(preselected)


def blueprint_selection(blueprint: Blueprint) -> ProjectSelection:
    """Resolve a blueprint to a selection, with nothing rendered.

    Uses the guided renderer with an empty key source: a blueprint answers
    every screen from the journal, so no screen ever reaches for a key or
    paints. That makes this the SAME code path the interactive flow runs,
    rather than a second implementation that could drift from it (an
    earlier headless renderer re-declared every screen default, giving the
    defaults two sources of truth). A screen that failed to auto-answer
    raises StopIteration here instead of silently taking a default.

    Imported inside the function: the guided module imports this one.
    """
    from ..cli.guided import GuidedSelectionUI

    ui = GuidedSelectionUI(keys=iter(()))
    ui.set_blueprint(blueprint)
    return run_project_selection(ui)
