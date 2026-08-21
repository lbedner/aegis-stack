"""Full-screen guided setup renderer for ``aegis init`` (issue #487).

A second :class:`~aegis.cli.interactive.SelectionUI` implementation. The
step engine in ``interactive.py`` drives selection and owns every rule
(worker pulls redis, scheduler persistence picks an engine, bracket-string
building); this renderer only decides how each question looks: a welcome
page, then one centered editorial screen per building block with a short
explanation, a derived "Pairs well with" line, and a compact Add / Skip
choice, with key hints pinned to a footer at the bottom of the screen.

Back navigation works by **rewind and replay**: every answered screen is
journaled, and ``esc`` pops the last answer and re-runs the whole engine,
replaying the journal silently (no rendering, no key reads) until it goes
live again at the previous screen. Because the guided path is pure — the
engine rebuilds a fresh ``ProjectSelection`` from answers alone and this
renderer never touches module state — replay keeps the rules single-source
and recomputes every downstream effect for free (un-pick worker and its
auto-added redis disappears; decline the scheduler and the persistence
question is never asked). The journal doubles as the breadcrumb trail
rendered under the header, so the trail always matches what going back
un-did.

Everything here is ephemeral: it draws in the terminal's alternate screen
buffer and restores the terminal untouched on exit. The resulting
``ProjectSelection`` is handed to the same ``aegis init`` pipeline as quick
mode, so the real build, project map, and next steps print to normal
scrollback exactly as before. No build or generation logic lives here.

Testability: pass ``keys=[...]`` to drive selection with scripted keypresses
and no terminal (rendering becomes a no-op and the welcome page is skipped),
so engine-driving — including esc/back replays — is unit-testable without a
TTY.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import typer
from rich.align import Align
from rich.cells import cell_len
from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ..blueprints import Blueprint
from ..blueprints.spec import ACCEPT_PREFIX, QKeys, pick_index, pick_multi
from ..constants import (
    AIProviders,
    PostgresProviders,
    StorageBackends,
    WorkerBackends,
)
from ..core.components import COMPONENTS, CORE_COMPONENTS
from ..core.plugins.spec import PluginSpec, pairs_well_with, required_names
from ..core.services import SERVICES
from .build_plan import BuildPlan, resolve_build_plan
from .guided_blueprints import BlueprintScreens
from .guided_chrome import (
    _NEON_DOCS_URL,
    ACCENT,
    BODY,
    LABEL,
    MIN_HEIGHT,
    MIN_WIDTH,
    MUTED,
    REQUIRES,
    RULE_STYLE,
    SIDEBAR_WIDTH,
    _Choice,
    _display_name,
    _docs_line,
    _docs_url,
    _fit_url,
    _g,
    _GoBack,
    _one_datastore_note,
    _read_key,
    _spec_blurb,
)
from .interactive import (
    ProjectSelection,
    get_skip_llm_sync_selection,
    run_project_selection,
)


def _copy_to_clipboard(text: str) -> bool:
    """Copy ``text`` to the system clipboard. Returns True on success.

    Tries the native clipboard tools first (pbcopy / xclip / xsel), then
    falls back to the OSC 52 escape sequence, which most modern terminals
    (iTerm2, recent Terminal.app, kitty, WezTerm) honor even over SSH.
    """
    import base64
    import shutil
    import subprocess
    import sys

    for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
                return True
            except Exception:  # noqa: BLE001 — fall through to OSC 52
                break
    try:
        payload = base64.b64encode(text.encode()).decode()
        sys.stdout.write(f"\x1b]52;c;{payload}\x07")
        sys.stdout.flush()
        return True
    except Exception:  # noqa: BLE001
        return False


class GuidedBuildError(Exception):
    """A build failed inside the guided experience.

    Carries the captured build output so the caller can print the full log
    to normal scrollback after the alternate screen is torn down — errors
    must never vanish with the ephemeral screen. The original exception is
    chained as ``__cause__``.
    """

    def __init__(self, log: str) -> None:
        super().__init__("guided build failed")
        self.log = log


class _GuidedBuildReporter:
    """``BuildReporter`` implementation feeding the guided build screen."""

    def __init__(self, ui: GuidedSelectionUI) -> None:
        self._ui = ui

    def step(self, key: str, label: str, detail: str = "") -> None:
        self._ui._on_build_event(key, label, detail, "running")

    def done(self, key: str, detail: str = "") -> None:
        self._ui._on_build_event(key, "", detail, "done")


@dataclass
class _JournalEntry:
    """One answered screen: the chosen index plus its breadcrumb effect."""

    idx: int
    crumb: str  # "push" | "amend" | "none"
    prev: tuple[str, str] | None = None  # previous crumb, for undoing an amend
    # Sidebar effects of an engine auto-add (``note_auto_added``) caused by
    # this answer, recorded for undoing on esc:
    auto_pushed: bool = False  # a new crumb was appended
    # a declined crumb was flipped to "✓ ...": (index, previous value)
    auto_prev: tuple[int, tuple[str, str]] | None = None


class GuidedSelectionUI(BlueprintScreens):
    """Centered, editorial full-screen renderer for the init selection engine.

    Real use: ``with GuidedSelectionUI(name) as ui:`` then
    :func:`run_guided_selection` — the alternate screen + raw input live for
    the duration. Test use: pass ``keys`` — rendering no-ops and each
    question reads the next scripted key (``"esc"`` exercises back/replay).
    """

    def __init__(
        self,
        project_name: str = "my-app",
        *,
        keys: Iterable[str] | None = None,
        console: Console | None = None,
    ) -> None:
        self.project_name = project_name
        # Bind the console to the real stdout stream NOW: the build phase
        # redirects sys.stdout into a capture buffer, and the alternate
        # screen must keep painting to the terminal regardless.
        import sys

        self._console = console or Console(file=sys.stdout)
        self._keys = iter(keys) if keys is not None else None
        self._section = ""
        self._live = None
        self._fd: int | None = None
        self._old_termios = None
        # Back-navigation journal + selections sidebar. The journal records
        # every answered screen; ``_cursor`` walks it during replay. Crumbs
        # are (name, detail) pairs kept in lock-step so popping an answer
        # also rewinds the sidebar.
        self._journal: list[_JournalEntry] = []
        self._cursor = 0
        self._resume_idx: int | None = None
        self._crumbs: list[tuple[str, str]] = []
        # Early-exit fast-forward ("f" finish / "s" skip to services):
        # while set, screens auto-answer their decline/default instead of
        # rendering. Each auto-answer is journaled like a real one, so esc
        # from the review still rewinds through them. One-shot per pass.
        self._ff: str | None = None  # None | "components" | "all"
        self._sections_seen = 0
        # Blueprint seeding: while set, every screen auto-answers from the
        # blueprint (journaled like real answers, same as fast-forward), so
        # the seeded pass lands on REVIEW with esc-revision fully working.
        self._blueprint: Blueprint | None = None

    # ----- lifecycle (no-op in scripted/test mode) ----------------------
    def __enter__(self) -> GuidedSelectionUI:
        if self._keys is None:
            import sys
            import termios
            import tty

            from rich.live import Live

            fd = sys.stdin.fileno()
            self._fd = fd
            self._old_termios = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._live = Live(console=self._console, screen=True, auto_refresh=False)
            self._live.start()
        return self

    def __exit__(self, *exc: object) -> None:
        fd, old = self._fd, self._old_termios
        if self._keys is None and fd is not None and old is not None:
            import termios

            if self._live is not None:
                self._live.stop()
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # ----- back-navigation journal ----------------------------------------
    @property
    def breadcrumbs(self) -> list[str]:
        """Display strings of every answered screen, in order."""
        return [f"{name} {detail}" for name, detail in self._crumbs]

    def begin_pass(self) -> None:
        """Start an engine pass: replay journaled answers from the top."""
        self._cursor = 0
        self._ff = None
        self._sections_seen = 0

    def pop_answer(self) -> bool:
        """Drop the most recent answer (and its crumb). False when empty."""
        if not self._journal:
            return False
        entry = self._journal.pop()
        if entry.auto_pushed and self._crumbs:
            self._crumbs.pop()  # the crumb an auto-add pushed for this answer
        if entry.auto_prev is not None:
            at, crumb_value = entry.auto_prev
            self._crumbs[at] = crumb_value  # un-flip the declined crumb
        if entry.crumb == "push" and self._crumbs:
            self._crumbs.pop()
        elif entry.crumb == "amend" and entry.prev is not None and self._crumbs:
            self._crumbs[-1] = entry.prev
        # Re-focus the re-asked screen on the answer being revised.
        self._resume_idx = entry.idx
        return True

    def reset_selection(self) -> None:
        """Forget every answer and any active blueprint: a clean slate.

        What esc on a blueprint's review uses to start over. Popping one
        answer at a time is meaningless there — the user answered no
        questions, they picked a stack — so the whole trail goes and the
        starting point asks again.
        """
        self._journal.clear()
        self._crumbs.clear()
        self._cursor = 0
        self._resume_idx = None
        self._ff = None
        self._blueprint = None

    @property
    def blueprint(self) -> Blueprint | None:
        """The active preset, if the flow is running one."""
        return self._blueprint

    @property
    def _with_sidebar(self) -> bool:
        """Whether the post-question screens carry the selections trail.

        A blueprint user answered no questions, so review, building, and the
        ready card drop it; a hand-picked stack keeps it. One predicate so
        the screens and their body widths can never disagree.
        """
        return self._blueprint is None

    def note_auto_added(self, name: str, detail: str = "") -> None:
        """An engine rule auto-added ``name``: surface it in the sidebar.

        No crumb for it yet -> push one; a declined screen's "✗" crumb ->
        flip it, since the project gets the component anyway; an accepted
        one is already accurate. The effect is attached to the most recent
        journal entry (the answer that caused the auto-add) so esc undoes
        it. Replays re-trigger this with the effect already applied — both
        branches no-op then, so nothing is double-recorded.
        """
        display = _display_name(name)
        mark = f"✓ {detail}" if detail else "✓"
        at = next(
            (i for i, (n, _) in enumerate(self._crumbs) if n == display),
            None,
        )
        if at is None:
            self._crumbs.append((display, mark))
            if self._journal:
                self._journal[-1].auto_pushed = True
        elif self._crumbs[at][1] == "✗":
            if self._journal:
                self._journal[-1].auto_prev = (at, self._crumbs[at])
            self._crumbs[at] = (display, mark)

    # ----- blueprint seeding ----------------------------------------------
    def set_blueprint(self, blueprint: Blueprint) -> None:
        """Activate a blueprint for the whole flow: every screen answers
        silently from it, so the pass lands on REVIEW; esc from there
        pops answers and re-asks them live."""
        self._blueprint = blueprint

    # ----- seams --------------------------------------------------------
    def _key(self) -> str:
        if self._keys is not None:
            return next(self._keys)
        assert self._fd is not None
        return _read_key(self._fd)

    def _paint(self, renderable: RenderableType) -> None:
        if self._live is not None:
            self._live.update(renderable, refresh=True)

    # ----- SelectionUI protocol -----------------------------------------
    def section(self, title: str, *, newline_before: bool = False) -> None:
        self._section = title
        self._sections_seen += 1
        # "Skip to services" ends when the engine enters the service phase
        # (the second section of a pass).
        if self._ff == "components" and self._sections_seen >= 2:
            self._ff = None

    def echo(self, message: str = "") -> None:  # transient status, not kept
        pass

    def success(self, message: str) -> None:  # transient status, not kept
        pass

    def confirm(
        self,
        prompt: str,
        *,
        default: bool = True,
        context: PluginSpec | None = None,
    ) -> bool:
        choices = [
            _Choice("yes", _g("choice.add", "Add")),
            _Choice("no", _g("choice.skip", "Skip")),
        ]
        idx = self._select(
            prompt.strip(),
            choices,
            default_idx=0 if default else 1,
            shortcuts={"y": 0, "n": 1},
            context=context,
            compact=True,
            # Component/service screens push a crumb ("Redis ✓"); secondary
            # confirms (scheduler persistence, auth-needs-db) leave the trail
            # alone — their outcome shows up via the chips that follow.
            crumb="push" if context is not None else "none",
            label=_display_name(context.name) if context is not None else "",
            qkey=f"{ACCEPT_PREFIX}{context.name}" if context is not None else "",
        )
        return choices[idx].value == "yes"

    def choose_scheduler_backend(self) -> str:
        """ONE screen for scheduler persistence: skip (memory) or an engine."""
        choices = [
            _Choice(
                StorageBackends.MEMORY,
                _g("choice.name.in_memory", "In-memory"),
                _g(
                    "choice.scheduler.memory",
                    "No persistence. Jobs reset on restart — skip if unsure.",
                ),
            ),
            _Choice(
                StorageBackends.SQLITE,
                "SQLite",
                _g(
                    "choice.scheduler.sqlite", "Persist job history in a file database."
                ),
            ),
            _Choice(
                StorageBackends.POSTGRES,
                "PostgreSQL",
                _g(
                    "choice.scheduler.postgres",
                    "Persist job history, production-grade.",
                ),
            ),
        ]
        return choices[
            self._select(
                _g(
                    "prompt.scheduler_backend",
                    "Scheduler persistence: keep job history across restarts?",
                ),
                choices,
                crumb="amend",
                note=_one_datastore_note(),
                qkey=QKeys.SCHEDULER_BACKEND,
            )
        ].value

    def choose_worker_backend(self) -> str:
        choices = [
            _Choice(
                WorkerBackends.ARQ,
                "arq",
                _g(
                    "choice.worker.arq",
                    "Simple, well-tested async worker with minimal "
                    "configuration. Best for I/O-bound tasks. The default.",
                ),
            ),
            _Choice(
                WorkerBackends.DRAMATIQ,
                "Dramatiq",
                _g(
                    "choice.worker.dramatiq",
                    "Multi-process actor model. Best for CPU-bound tasks that "
                    "benefit from multiple OS processes.",
                ),
            ),
            _Choice(
                WorkerBackends.TASKIQ,
                "TaskIQ",
                _g(
                    "choice.worker.taskiq",
                    "Async-native with per-queue brokers and Redis Streams "
                    "transport with acknowledgements.",
                ),
            ),
        ]
        return choices[
            self._select(
                _g("prompt.worker_backend", "Pick a worker backend"),
                choices,
                crumb="amend",
                qkey=QKeys.WORKER_BACKEND,
            )
        ].value

    def choose_database_engine(self, context: str) -> tuple[str, str | None]:
        choices = [
            _Choice(
                StorageBackends.SQLITE,
                "SQLite",
                _g(
                    "choice.db.sqlite",
                    "Zero-config file database. Great for development.",
                ),
            ),
            _Choice(
                StorageBackends.POSTGRES,
                "PostgreSQL",
                _g("choice.db.postgres", "Production-grade, pooled connections."),
            ),
        ]
        engine = choices[
            self._select(
                _g(
                    "prompt.database_engine",
                    "Database engine for {context}",
                    context=context,
                ),
                choices,
                crumb="amend",
                note=_one_datastore_note(),
                qkey=QKeys.DATABASE_ENGINE,
            )
        ].value
        if engine == StorageBackends.POSTGRES:
            return engine, self.choose_postgres_provider(context, crumb="amend")
        return engine, None

    def choose_postgres_provider(self, context: str, *, crumb: str = "none") -> str:
        """ONE screen for the PostgreSQL host: local container vs Neon (vs ...).

        The direct database path amends the Database crumb; indirect paths
        (scheduler persistence, AI storage) pass no crumb — their
        ``note_auto_added`` call carries the chosen host into the sidebar.
        """
        choices = [
            _Choice(
                PostgresProviders.CONTAINER,
                "Local container",
                _g(
                    "choice.db_provider.container",
                    "Local postgres:16 container, dev and prod.",
                ),
            ),
            _Choice(
                PostgresProviders.NEON,
                "Neon",
                _g(
                    "choice.db_provider.neon",
                    "Serverless Postgres: cloud in prod, local container in dev.",
                ),
                docs_url=_NEON_DOCS_URL,
            ),
        ]
        return choices[
            self._select(
                _g(
                    "prompt.postgres_provider",
                    "PostgreSQL host for {context}",
                    context=context,
                ),
                choices,
                crumb=crumb,
                qkey=QKeys.POSTGRES_PROVIDER,
                note=_g(
                    "note.one_database_host",
                    "One database per project: this host serves everything "
                    "that stores data.",
                ),
            )
        ].value

    def configure_auth(self, service_name: str) -> str:
        choices = [
            _Choice(
                "basic",
                "Basic",
                _g("choice.auth.basic", "Email and password with JWT sessions."),
            ),
            _Choice(
                "rbac", "RBAC", _g("choice.auth.rbac", "Adds roles and permissions.")
            ),
            _Choice("org", "Org", _g("choice.auth.org", "Multi-tenant organizations.")),
        ]
        return choices[
            self._select(
                _g("prompt.auth_level", "Authentication level"),
                choices,
                crumb="amend",
                qkey=QKeys.AUTH_LEVEL,
            )
        ].value

    def configure_ai(
        self, service_name: str, existing_engine: str | None = None
    ) -> tuple[str, str, list[str], bool, bool]:
        framework = [
            _Choice(
                "pydantic-ai",
                "Pydantic AI",
                _g(
                    "choice.framework.pydantic_ai",
                    "Typed and lightweight. The default.",
                ),
            ),
            _Choice(
                "langchain",
                "LangChain",
                _g("choice.framework.langchain", "Large ecosystem, many integrations."),
            ),
        ]
        fw = framework[
            self._select(
                _g("prompt.ai_framework", "AI framework"),
                framework,
                crumb="amend",
                qkey=QKeys.AI_FRAMEWORK,
            )
        ].value
        if existing_engine:
            # One datastore, used everywhere: the project already has a
            # database, so conversations persist to it — no storage screen.
            return self._configure_ai_extras(fw, existing_engine)
        backend = [
            _Choice(
                StorageBackends.MEMORY,
                _g("choice.name.in_memory", "In-memory"),
                _g("choice.storage.memory", "No history, nothing to set up."),
            ),
            _Choice(
                StorageBackends.SQLITE,
                "SQLite",
                _g(
                    "choice.storage.sqlite",
                    "Persistent chat history in a file database.",
                ),
            ),
            _Choice(
                StorageBackends.POSTGRES,
                "PostgreSQL",
                _g("choice.storage.postgres", "Persistent and production-grade."),
            ),
        ]
        be = backend[
            self._select(
                _g("prompt.ai_storage", "AI conversation storage"),
                backend,
                crumb="amend",
                note=_one_datastore_note(),
                qkey=QKeys.AI_STORAGE,
            )
        ].value
        return self._configure_ai_extras(fw, be)

    def _configure_ai_extras(
        self, fw: str, be: str
    ) -> tuple[str, str, list[str], bool, bool]:
        provider_choices = [
            _Choice(
                provider_id,
                name,
                f"{_g(f'choice.provider.{provider_id}.desc', description)}. "
                f"{_g(f'choice.provider.{provider_id}.pricing', pricing)}.",
            )
            for provider_id, name, description, pricing, _ in AIProviders.PROVIDER_INFO
        ]
        preselected = {
            i
            for i, (_, _, _, _, recommended) in enumerate(AIProviders.PROVIDER_INFO)
            if recommended
        }
        picked = self._multi_select(
            _g("prompt.ai_providers", "AI providers: pick any to wire in"),
            provider_choices,
            preselected,
            crumb="amend",
            qkey=QKeys.AI_PROVIDERS,
        )
        # Same fallback as quick mode: nothing picked means the free tier.
        providers = [provider_choices[i].value for i in picked] or list(
            AIProviders.INTERACTIVE_DEFAULTS
        )

        # Optional capabilities. A skip contributes an empty crumb value,
        # which _record drops — only enabled extras show in the sidebar.
        rag_choices = [
            _Choice("rag", _g("choice.add", "Add")),
            _Choice("", _g("choice.skip", "Skip")),
        ]
        rag = (
            rag_choices[
                self._select(
                    _g(
                        "prompt.ai_rag",
                        "Add RAG: chat grounded in your own docs and code?",
                    ),
                    rag_choices,
                    default_idx=1,
                    shortcuts={"y": 0, "n": 1},
                    compact=True,
                    crumb="amend",
                    qkey=QKeys.AI_RAG,
                )
            ].value
            == "rag"
        )
        voice_choices = [
            _Choice("voice", _g("choice.add", "Add")),
            _Choice("", _g("choice.skip", "Skip")),
        ]
        voice = (
            voice_choices[
                self._select(
                    _g(
                        "prompt.ai_voice",
                        "Add voice: text-to-speech and speech-to-text?",
                    ),
                    voice_choices,
                    default_idx=1,
                    shortcuts={"y": 0, "n": 1},
                    compact=True,
                    crumb="amend",
                    qkey=QKeys.AI_VOICE,
                )
            ].value
            == "voice"
        )
        return be, fw, providers, rag, voice

    # ----- welcome page ---------------------------------------------------
    def show_welcome(self) -> None:
        """Intro page; blocks for enter. Skipped (zero keys) in scripted mode."""
        if self._keys is not None:
            return

        width = self._content_width(sidebar=False)
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        grid.add_row(
            Text(
                _g("welcome.title", "AEGIS STACK"),
                style=f"bold {ACCENT}",
                justify="center",
            )
        )
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g("welcome.tagline", "Production-ready Python apps from day one."),
                style="bold",
                justify="center",
            )
        )
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g(
                    "welcome.body",
                    "This guided setup walks through each building block "
                    "with a short explanation so you can decide what your "
                    "project needs. Pick only what you want now; everything "
                    "can be added later with 'aegis add'.",
                ),
                style=BODY,
                justify="center",
            )
        )
        hints = Text.assemble(
            ("enter", ACCENT),
            (f" {_g('hint.begin', 'begin')}    ", LABEL),
            ("q", ACCENT),
            (f" {_g('hint.quit', 'quit')}", LABEL),
        )
        while True:
            self._paint(self._frame(grid, hints, sidebar=False))
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key in ("\r", "\n"):
                return

    def show_core_stack(self) -> None:
        """The preselected foundation: backend + frontend on one page.

        Informational only — these ship with every project, so there is
        nothing to answer beyond next. Skipped (zero keys) in scripted mode
        like the welcome page, keeping engine key counts valid.
        """
        if self._keys is not None:
            return

        width = self._content_width(sidebar=False)
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        grid.add_row(
            Text(
                _g("corestack.title", "INCLUDED IN EVERY PROJECT"),
                style=LABEL,
                justify="center",
            )
        )
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g(
                    "corestack.body",
                    "Every Aegis project starts with these two, wired "
                    "together and ready to run.",
                ),
                style=BODY,
                justify="center",
            )
        )
        for name in CORE_COMPONENTS:
            spec = COMPONENTS[name]
            grid.add_row(Text())
            grid.add_row(Text())
            title = Text(justify="center")
            title.append(_display_name(name), style="bold")
            title.append("   ")
            title.append(spec.description, style=ACCENT)
            grid.add_row(title)
            grid.add_row(Text())
            grid.add_row(Text(_spec_blurb(spec), style=BODY, justify="center"))
            docs = _docs_url(spec)
            if docs:
                grid.add_row(Text())
                grid.add_row(_docs_line(docs, width))

        hints = Text.assemble(
            ("enter", ACCENT),
            (f" {_g('hint.next', 'next')}    ", LABEL),
            ("q", ACCENT),
            (f" {_g('hint.quit', 'quit')}", LABEL),
        )
        while True:
            self._paint(self._frame(grid, hints, sidebar=False))
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key in ("\r", "\n"):
                return

    # ----- review screen --------------------------------------------------
    def show_review(self, plan: BuildPlan) -> str:
        """Build summary + confirm. Returns ``"build"`` or ``"back"``.

        ``f``/``d`` toggle the file and dependency detail panes; ``esc``
        returns to the questions (the caller pops the journal); ``enter``
        confirms the build.
        """
        pane: str | None = None
        hints = Text.assemble(
            ("f", ACCENT),
            (f" {_g('hint.files', 'files')}    ", LABEL),
            ("d", ACCENT),
            (f" {_g('hint.deps', 'deps')}    ", LABEL),
            ("enter", ACCENT),
            (f" {_g('hint.build', 'build')}    ", LABEL),
            ("esc", ACCENT),
            (f" {_g('hint.back', 'back')}    ", LABEL),
            ("q", ACCENT),
            (f" {_g('hint.quit', 'quit')}", LABEL),
        )
        while True:
            # No selections sidebar on a blueprint's review: the trail is
            # a record of questions this user never answered, and showing
            # it invites esc-ing back into free-flow mode, which is the one
            # thing choosing a ready-made stack was meant to avoid. Blank
            # canvas keeps its sidebar — there the trail is their own work.
            self._paint(
                self._frame(
                    self._review_body(plan, pane),
                    hints,
                    sidebar=self._with_sidebar,
                )
            )
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key == "esc":
                return "back"
            if key in ("\r", "\n"):
                return "build"
            if key == "f":
                pane = None if pane == "files" else "files"
            elif key == "d":
                pane = None if pane == "deps" else "deps"

    def _review_body(self, plan: BuildPlan, pane: str | None) -> RenderableType:
        width = self._content_width(sidebar=self._with_sidebar)
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        grid.add_row(
            Text(_g("review.title", "YOUR BUILD"), style=LABEL, justify="center")
        )
        grid.add_row(Text())
        grid.add_row(Text(plan.project_name, style="bold", justify="center"))
        grid.add_row(Text())

        # Core stack ships with every project; list it first so the build
        # summary is the whole project, not just what was chosen on top of it.
        core = Text()
        core.append(f"{_g('review.core', 'Core:')}            ", style=LABEL)
        core.append(" · ".join(CORE_COMPONENTS), style=BODY)
        grid.add_row(core)
        grid.add_row(Text())

        auto = set(plan.service_component_map) | set(plan.auto_added_components)

        def _component_row(label: str, names: list[str]) -> Text:
            row = Text()
            row.append(label, style=LABEL)
            for i, comp in enumerate(names):
                if i:
                    row.append(" · ", style=RULE_STYLE)
                row.append(comp, style=BODY)
                if comp.split("[", 1)[0] in auto or comp in auto:
                    row.append(f" {_g('review.auto', 'auto')}", style=MUTED)
            return row

        # Grouped by type: an optional frontend is not infrastructure. Labels
        # are padded to the same width as Core:/Services: above.
        if plan.infrastructure:
            grid.add_row(
                _component_row(
                    f"{_g('review.infrastructure', 'Infrastructure:')}  ",
                    plan.infrastructure,
                )
            )
        if plan.frontend:
            grid.add_row(
                _component_row(
                    f"{_g('review.web_frontend', 'Web frontend:')}    ",
                    plan.frontend,
                )
            )
        if plan.services:
            grid.add_row(Text())
            grid.add_row(
                Text.assemble(
                    (f"{_g('review.services', 'Services:')}        ", LABEL),
                    (" · ".join(plan.services), BODY),
                )
            )
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g(
                    "review.counts",
                    "{files} component files · {deps} dependencies",
                    files=len(plan.template_files),
                    deps=len(plan.dependencies),
                ),
                style=MUTED,
            )
        )
        # Nothing chosen here is permanent. Said plainly on the last screen
        # before the build, because that is where it reads as reassurance
        # rather than as a footnote nobody reaches.
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g(
                    "review.grows",
                    "Anything missing can be added later: aegis add, "
                    "aegis add-service.",
                ),
                style=LABEL,
            )
        )

        if pane is not None:
            items = plan.template_files if pane == "files" else plan.dependencies
            # Fit the pane to the terminal; keep the head, summarize the rest.
            avail = max(3, self._console.size.height - 18)
            grid.add_row(Text())
            grid.add_row(
                Text(
                    _g("review.files_pane", "COMPONENT FILES")
                    if pane == "files"
                    else _g("review.deps_pane", "DEPENDENCIES"),
                    style=LABEL,
                )
            )
            for item in items[:avail]:
                grid.add_row(Text(f"  {item}", style=BODY))
            if len(items) > avail:
                grid.add_row(
                    Text(
                        f"  {_g('review.more', '… +{n} more', n=len(items) - avail)}",
                        style=MUTED,
                    )
                )

        grid.add_row(Text())
        grid.add_row(
            Text(
                f"▸ {_g('review.build', 'Build {name}', name=plan.project_name)}",
                style=f"bold {ACCENT}",
                justify="center",
            )
        )
        return grid

    # ----- build + done screens --------------------------------------------
    def build_reporter(self, plan: BuildPlan) -> _GuidedBuildReporter:
        """Observer for the generation pipeline; repaints per step event.

        Step events arrive while sys.stdout is redirected into the capture
        buffer — painting works because the console was bound to the real
        terminal stream at construction.
        """
        self._build_name = plan.project_name
        self._build_steps: list[dict[str, str]] = []
        return _GuidedBuildReporter(self)

    def _on_build_event(self, key: str, label: str, detail: str, state: str) -> None:
        for entry in self._build_steps:
            if entry["key"] == key:
                entry["state"] = state
                if label:
                    entry["label"] = label
                if detail:
                    entry["detail"] = detail
                break
        else:
            self._build_steps.append(
                {"key": key, "label": label, "detail": detail, "state": state}
            )
        self.show_building_progress()

    def show_building(self, plan: BuildPlan) -> None:
        """Initial build frame (no steps yet); reporter events take over."""
        self._build_name = plan.project_name
        self._build_steps = []
        self.show_building_progress()

    def show_building_progress(self) -> None:
        width = self._content_width(sidebar=self._with_sidebar)
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        grid.add_row(
            Text(
                _g("building.title", "Building {name} …", name=self._build_name),
                style="bold",
                justify="center",
            )
        )
        grid.add_row(Text())
        if not self._build_steps:
            grid.add_row(
                Text(
                    _g("building.preparing", "Preparing …"),
                    style=MUTED,
                    justify="center",
                )
            )
        for entry in self._build_steps:
            label = _g(f"build.{entry['key']}", entry["label"])
            running = entry["state"] == "running"
            line = Text()
            line.append(
                "  → " if running else "  ✔ ", style=ACCENT if running else "green"
            )
            line.append(f"{label:32}", style="white" if running else BODY)
            if entry["detail"]:
                line.append(entry["detail"], style=LABEL)
            grid.add_row(line)
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g(
                    "building.note",
                    "This can take a minute or two; uv does the heavy lifting.",
                ),
                style=MUTED,
                justify="center",
            )
        )
        self._paint(
            # A blueprint build drops the sidebar for the same reason its
            # review does: the trail records questions this user never
            # answered. A hand-picked stack keeps it — there it is their
            # own work, and worth watching land.
            self._frame(
                grid,
                Text(_g("hint.building", "building …"), style=LABEL),
                sidebar=self._with_sidebar,
            )
        )

    def show_done(
        self,
        plan: BuildPlan,
        project_path: object,
        replay: str | None,
        project_map: str = "",
    ) -> None:
        """End card: ready banner, next steps, replay command. Enter to finish.

        The replay command is always shown in full — the card widens up to
        the content region and wraps on narrow terminals. ``c`` copies the
        command to the clipboard (selecting wrapped alt-screen text would
        inject line breaks), and the persistent receipt printed after
        finish carries it unwrapped.
        """
        copied = False
        while True:
            self._paint(
                self._frame(
                    self._done_body(plan, project_path, replay, copied, project_map),
                    self._done_hints(replay),
                    # Same rule as review and building: a blueprint user has
                    # no answer trail of their own, and the project map on
                    # this card already says what they got.
                    sidebar=self._with_sidebar,
                )
            )
            key = self._key()
            if key == "c" and replay:
                copied = _copy_to_clipboard(replay)
            elif key in ("\r", "\n", "q", "\x03"):
                return

    def _region_width(self, *, sidebar: bool = True) -> int:
        """Usable width of the content region (right of the sidebar)."""
        total = self._console.size.width
        if not sidebar:
            return max(40, total - 12)
        gutters = 2 * SIDEBAR_WIDTH if self._balanced() else SIDEBAR_WIDTH + 8
        return max(40, total - gutters - 4)

    def _done_body(
        self,
        plan: BuildPlan,
        project_path: object,
        replay: str | None,
        copied: bool,
        project_map: str = "",
    ) -> RenderableType:
        # The card widens beyond the usual 68-char prose column when the
        # replay command needs the room, up to the full content region —
        # the command must be fully visible, never ellipsized.
        width = self._content_width(sidebar=self._with_sidebar)
        if replay:
            width = min(
                self._region_width(sidebar=self._with_sidebar),
                max(width, len(replay) + 4),
            )
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        grid.add_row(
            Text(
                _g("done.ready", "{name} is ready", name=plan.project_name),
                style=f"bold {ACCENT}",
                justify="center",
            )
        )
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g("done.body", "Project generated and dependencies installed."),
                style=BODY,
                justify="center",
            )
        )
        if project_map:
            grid.add_row(Text())
            grid.add_row(
                Text(_g("done.project_structure", "PROJECT STRUCTURE"), style=LABEL)
            )
            # Drop the captured title line; the tree starts at "<name>/".
            lines = project_map.rstrip().splitlines()
            start = next(
                (i for i, ln in enumerate(lines) if ln.rstrip().endswith("/")), 0
            )
            for line in lines[start:]:
                if "←" in line:
                    left, _, right = line.partition("←")
                    row = Text(f"  {left}", style=BODY)
                    row.append(f"← {right.strip()}", style=LABEL)
                else:
                    row = Text(f"  {line}", style=BODY)
                grid.add_row(row)
        grid.add_row(Text())
        grid.add_row(Text(_g("done.next_steps", "NEXT STEPS"), style=LABEL))
        grid.add_row(Text(f"  cd {project_path}", style=BODY))
        grid.add_row(Text("  make serve", style=BODY))
        grid.add_row(Text("  Overseer: http://localhost:8000/dashboard/", style=BODY))
        if replay:
            grid.add_row(Text())
            grid.add_row(
                Text(_g("done.recreate", "RECREATE THIS STACK ANYTIME"), style=LABEL)
            )
            # Full command, always: wraps on narrow terminals rather than
            # truncating. Copy via the c key (or the receipt) — selecting
            # wrapped alt-screen text would inject line breaks.
            grid.add_row(Text(f"  {replay}", style=ACCENT))
            note = (
                _g("done.copied", "Copied to clipboard ✓")
                if copied
                else _g(
                    "done.copy_note",
                    "Press c to copy; the full command also prints "
                    "below after you finish.",
                )
            )
            grid.add_row(Text(f"  {note}", style="green" if copied else MUTED))
        return grid

    def _done_hints(self, replay: str | None) -> Text:
        hints = Text()
        if replay:
            hints.append("c", style=ACCENT)
            hints.append(f" {_g('hint.copy', 'copy command')}    ", style=LABEL)
        hints.append("enter", style=ACCENT)
        hints.append(f" {_g('hint.finish', 'finish')}", style=LABEL)
        return hints

    # ----- the select loop ----------------------------------------------
    def _select(
        self,
        prompt: str,
        choices: list[_Choice],
        *,
        default_idx: int = 0,
        shortcuts: dict[str, int] | None = None,
        context: PluginSpec | None = None,
        compact: bool = False,
        crumb: str = "none",
        label: str = "",
        note: str | None = None,
        qkey: str = "",
    ) -> int:
        # Replay path: hand back the journaled answer, render nothing.
        if self._cursor < len(self._journal):
            entry = self._journal[self._cursor]
            self._cursor += 1
            return entry.idx

        shortcuts = shortcuts or {}
        idx = default_idx
        if self._resume_idx is not None:
            # This is the screen the user backed into; focus their old answer.
            idx = min(self._resume_idx, len(choices) - 1)
            self._resume_idx = None
        elif self._blueprint is not None:
            # A blueprint answers EVERY remaining screen silently
            # (journaled like keypresses), so the seeded pass lands on
            # REVIEW; esc from there pops an answer and re-asks it live,
            # and forward replay re-seeds from the blueprint again.
            idx = pick_index(
                self._blueprint, qkey, [c.value for c in choices], default_idx
            )
            return self._record(idx, choices, crumb, label)

        in_components = self._sections_seen < 2
        hints = Text.assemble(
            ("←/→", ACCENT),
            (f" {_g('hint.move', 'move')}    ", LABEL),
            ("enter", ACCENT),
            (f" {_g('hint.select', 'select')}    ", LABEL),
            ("esc", ACCENT),
            (f" {_g('hint.back', 'back')}    ", LABEL),
            *(
                (
                    ("s", ACCENT),
                    (f" {_g('hint.services', 'skip to services')}    ", LABEL),
                )
                if in_components
                else ()
            ),
            ("f", ACCENT),
            (f" {_g('hint.finish', 'finish')}    ", LABEL),
            ("q", ACCENT),
            (f" {_g('hint.quit', 'quit')}", LABEL),
        )
        while True:
            if self._ff is not None:
                # Fast-forward: decline confirms, take the default on chip
                # screens (the user already accepted whatever spawned them).
                return self._record(
                    shortcuts.get("n", default_idx), choices, crumb, label
                )
            self._paint(
                self._frame(
                    self._body(prompt, choices, idx, context, compact, note=note),
                    hints,
                )
            )
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key == "esc":
                raise _GoBack()
            if key == "f":
                self._ff = "all"
                continue
            if key == "s" and self._sections_seen < 2:
                self._ff = "components"
                continue
            if key in shortcuts:
                return self._record(shortcuts[key], choices, crumb, label)
            if key in ("left", "h"):
                idx = (idx - 1) % len(choices)
            elif key in ("right", "l"):
                idx = (idx + 1) % len(choices)
            elif key in ("\r", "\n"):
                return self._record(idx, choices, crumb, label)

    def _record(self, idx: int, choices: list[_Choice], crumb: str, label: str) -> int:
        """Journal a live answer and apply its sidebar effect."""
        self._record_value(idx, choices[idx].value, crumb, label)
        return idx

    def _record_value(self, idx: int, value: str, crumb: str, label: str) -> None:
        """Journal an answer (``idx`` is the replay payload) and apply its
        sidebar effect. ``_select`` stores the chosen index; ``_multi_select``
        stores a bitmask of toggled indices."""
        prev: tuple[str, str] | None = None
        if crumb == "push":
            mark = "✓" if value == "yes" else "✗"
            self._crumbs.append((label, mark))
        elif crumb == "amend" and self._crumbs and value:
            prev = self._crumbs[-1]
            name, detail = prev
            self._crumbs[-1] = (name, f"{detail} {value}")
        self._journal.append(_JournalEntry(idx, crumb, prev))
        self._cursor += 1

    def _multi_select(
        self,
        prompt: str,
        choices: list[_Choice],
        preselected: set[int],
        *,
        crumb: str = "none",
        qkey: str = "",
    ) -> list[int]:
        """Vertical checkbox list with a trailing Continue entry.

        Enter means "act on the focused thing" everywhere in the guided
        setup, so here it TOGGLES the focused option (space works too);
        the screen only advances via enter on Continue. Returns the
        selected indices in choice order. Journaled as a bitmask in the
        entry's ``idx`` so esc/replay round-trips the whole selection
        through the same machinery as single selects.
        """
        # Replay path: hand back the journaled bitmask, render nothing.
        if self._cursor < len(self._journal):
            entry = self._journal[self._cursor]
            self._cursor += 1
            return [i for i in range(len(choices)) if entry.idx >> i & 1]

        selected = set(preselected)
        if self._resume_idx is not None:
            # Backed into this screen: restore the previous selection.
            selected = {i for i in range(len(choices)) if self._resume_idx >> i & 1}
            self._resume_idx = None
        cursor = 0
        continue_idx = len(choices)  # the trailing Continue row

        hints = Text.assemble(
            ("↑/↓", ACCENT),
            (f" {_g('hint.move', 'move')}    ", LABEL),
            ("enter/space", ACCENT),
            (f" {_g('hint.toggle', 'toggle')}    ", LABEL),
            ("esc", ACCENT),
            (f" {_g('hint.back', 'back')}    ", LABEL),
            ("q", ACCENT),
            (f" {_g('hint.quit', 'quit')}", LABEL),
        )

        def _accept() -> list[int]:
            picked = sorted(selected)
            bitmask = sum(1 << i for i in picked)
            value = ",".join(choices[i].value for i in picked)
            self._record_value(bitmask, value, crumb, "")
            return picked

        if self._blueprint is not None:
            # Blueprint answers silently, journaled like a live pick.
            selected = pick_multi(
                self._blueprint, qkey, [c.value for c in choices], preselected
            )
            return _accept()

        while True:
            if self._ff is not None:
                # Fast-forward: keep whatever is currently checked.
                return _accept()
            self._paint(
                self._frame(self._multi_body(prompt, choices, cursor, selected), hints)
            )
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key == "esc":
                raise _GoBack()
            if key == "f":
                self._ff = "all"
                continue
            if key in ("up", "k"):
                cursor = (cursor - 1) % (continue_idx + 1)
            elif key in ("down", "j"):
                cursor = (cursor + 1) % (continue_idx + 1)
            elif key == " " and cursor != continue_idx:
                selected.symmetric_difference_update({cursor})
            elif key in ("\r", "\n"):
                if cursor != continue_idx:
                    selected.symmetric_difference_update({cursor})
                    continue
                return _accept()

    def _multi_body(
        self,
        prompt: str,
        choices: list[_Choice],
        cursor: int,
        selected: set[int],
    ) -> RenderableType:
        width = self._content_width()
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        if self._section:
            grid.add_row(Text(self._section.upper(), style=LABEL, justify="center"))
            grid.add_row(Text())
        grid.add_row(Text(prompt, style="bold", justify="center"))
        grid.add_row(Text())
        grid.add_row(
            Text(
                _g(
                    "multi.hint",
                    "Check as many as you like, then pick Continue.",
                ),
                style=LABEL,
                justify="center",
            )
        )
        grid.add_row(Text())
        # A left-aligned checklist centered as a block: every row shows a
        # toggle marker, so unchecked entries still read as checkable.
        checklist = Table.grid(padding=(0, 0))
        checklist.add_column()
        for i, choice in enumerate(choices):
            row = Text()
            if i in selected:
                row.append("✓ ", style=ACCENT)
            else:
                row.append("· ", style=MUTED)
            row.append(
                choice.title,
                style="reverse bold"
                if i == cursor
                else (BODY if i in selected else MUTED),
            )
            checklist.add_row(row)
        checklist.add_row(Text())
        cont = Text("  ")
        cont.append(
            f"▸ {_g('choice.continue', 'Continue')}",
            style="reverse bold" if cursor == len(choices) else ACCENT,
        )
        checklist.add_row(cont)
        grid.add_row(Align(checklist, align="center"))
        grid.add_row(Text())
        focused_body = "" if cursor == len(choices) else choices[cursor].body
        grid.add_row(Text(focused_body or " ", style=MUTED, justify="center"))
        return grid

    # ----- rendering ----------------------------------------------------
    def _balanced(self) -> bool:
        """True when there's room to mirror the sidebar with a right spacer,
        which puts the body on the true screen midline instead of the
        center of the leftover region."""
        return self._console.size.width - 2 * SIDEBAR_WIDTH - 4 >= 48

    def _content_width(self, *, sidebar: bool = True) -> int:
        """Width of the body column.

        With a sidebar, the mirrored gutters that center the body cost two
        sidebar widths. Without one the body owns the row, so it keeps the
        margins but takes a wider measure — still bounded, because prose
        past ~80 columns is harder to read, not easier.
        """
        width = self._console.size.width
        if not sidebar:
            return max(40, min(80, width - 12))
        avail = width - (2 * SIDEBAR_WIDTH + 4 if self._balanced() else 12)
        return max(40, min(68, avail))

    def _sidebar(self) -> RenderableType:
        """The selections panel: components and services under their own
        subtitles, each decided item's name with its choice indented on the
        line below (more information = more indent)."""
        _, height = self._console.size
        grid = Table.grid(padding=(0, 1))
        grid.add_column(width=SIDEBAR_WIDTH - 4)

        # Partition by display name so auto-added components (a Database
        # crumb pushed during a service screen) still file under
        # COMPONENTS, whatever their journal position. The preselected core
        # stack leads the section; it ships with every project, so it lives
        # here at render time rather than in the undo journal.
        service_names = {_display_name(name) for name in SERVICES}
        core = [(_display_name(name), "✓") for name in CORE_COMPONENTS]
        sections = [
            (
                _g("sidebar.components", "COMPONENTS"),
                core + [c for c in self._crumbs if c[0] not in service_names],
            ),
            (
                _g("sidebar.services", "SERVICES"),
                [c for c in self._crumbs if c[0] in service_names],
            ),
        ]
        sections = [(title, items) for title, items in sections if items]

        # Two lines per entry plus three per section header (title, the
        # blank under it, the separator); drop the oldest entries when the
        # terminal is too short to show them all.
        avail = max(0, height - 5)

        def _lines() -> int:
            return sum(3 + 2 * len(items) for _, items in sections)

        truncated = False
        while sections and _lines() > avail:
            sections[0][1].pop(0)
            truncated = True
            if not sections[0][1]:
                sections.pop(0)
        if truncated:
            grid.add_row(Text("…", style=LABEL))

        for index, (title, items) in enumerate(sections):
            if index:
                grid.add_row(Text())
            grid.add_row(Text(title, style=LABEL))
            grid.add_row(Text())
            for name, detail in items:
                skipped = detail.startswith("✗")
                grid.add_row(Text(name, style=MUTED if skipped else BODY))
                grid.add_row(Text(f"  {detail}", style=MUTED if skipped else ACCENT))
        return Padding(grid, (1, 0, 0, 2))

    def _frame(
        self, body: RenderableType, hints: Text, *, sidebar: bool = True
    ) -> RenderableType:
        """Header / selections sidebar + centered body / bottom-pinned footer."""
        width, height = self._console.size
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return Align(
                Text(
                    _g(
                        "screen.too_small",
                        "Terminal too small. Resize to at least {w}x{h}.",
                        w=MIN_WIDTH,
                        h=MIN_HEIGHT,
                    ),
                    style=MUTED,
                ),
                align="center",
                vertical="middle",
            )

        header = Table.grid(expand=True)
        header.add_column(justify="left")
        header.add_column(justify="right")
        header.add_row(
            f"[bold]aegis init[/] [{LABEL}]· {self.project_name}[/]",
            f"[{LABEL}]{_g('header.label', 'guided setup')}[/]",
        )

        content = Layout(Align(body, align="center", vertical="middle"), name="content")
        if sidebar:
            main = Layout(name="main")
            columns = [
                Layout(self._sidebar(), name="sidebar", size=SIDEBAR_WIDTH),
                content,
            ]
            if self._balanced():
                # Blank mirror of the sidebar: keeps the body centered on
                # the true screen midline rather than pushed right. (A
                # single space, not "": rich shows a debug placeholder for
                # falsy layout content.)
                columns.append(Layout(Text(" "), name="spacer", size=SIDEBAR_WIDTH))
            main.split_row(*columns)
        else:
            main = content

        layout = Layout()
        layout.split_column(
            Layout(Group(header, Rule(style=RULE_STYLE)), name="header", size=2),
            main,
            Layout(
                Group(Rule(style=RULE_STYLE), Align(hints, align="center")),
                name="footer",
                size=2,
            ),
        )
        return layout

    def _body(
        self,
        prompt: str,
        choices: list[_Choice],
        cursor: int,
        context: PluginSpec | None,
        compact: bool,
        note: str | None = None,
    ) -> RenderableType:
        width = self._content_width()
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)

        if self._section:
            grid.add_row(Text(self._section.upper(), style=LABEL, justify="center"))
            grid.add_row(Text())

        if context is not None:
            grid.add_row(
                Text(_display_name(context.name), style="bold", justify="center")
            )
            grid.add_row(Text())
            grid.add_row(Text(_spec_blurb(context), style=BODY))
            requires = required_names(context, exclude=CORE_COMPONENTS)
            if requires:
                grid.add_row(Text())
                grid.add_row(
                    Text.assemble(
                        (f"{_g('screen.requires', 'Requires:')}  ", LABEL),
                        (" · ".join(_display_name(r) for r in requires), REQUIRES),
                        (
                            f"   {_g('screen.added_automatically', '(added automatically)')}",
                            LABEL,
                        ),
                    )
                )
            pairs = pairs_well_with(
                context,
                [*COMPONENTS.values(), *SERVICES.values()],
                exclude=CORE_COMPONENTS,
            )
            if pairs:
                grid.add_row(Text())
                grid.add_row(
                    Text.assemble(
                        (f"{_g('screen.pairs', 'Pairs well with:')}  ", LABEL),
                        (" · ".join(_display_name(p) for p in pairs), BODY),
                    )
                )
            docs = _docs_url(context)
            if docs:
                grid.add_row(Text())
                # cell_len, not len: CJK locales render the label at two
                # cells per character and an overflowing row ellipsizes
                # the URL into a broken link. When even the shortest URL
                # form can't fit beside the label, the URL gets its own
                # full-width line instead.
                label = f"{_g('screen.docs', 'Docs:')}  "
                available = width - cell_len(label)
                display = _fit_url(docs, available)
                if cell_len(display) > available:
                    grid.add_row(_docs_line(docs, width))
                else:
                    docs_line = Text.assemble((label, LABEL), (display, MUTED))
                    docs_line.no_wrap = True
                    grid.add_row(docs_line)
            grid.add_row(Text())
            # The engine prompt carries quick-mode hints like "(will
            # auto-add Redis)" that the Requires line already covers here,
            # so context screens ask a clean question instead.
            grid.add_row(
                Text(
                    _g(
                        "screen.add_question",
                        "Add {name}?",
                        name=_display_name(context.name),
                    ),
                    justify="center",
                )
            )
        else:
            grid.add_row(Text(prompt, style="bold", justify="center"))
            if note:
                grid.add_row(Text())
                grid.add_row(Text(note, style=MUTED, justify="center"))

        grid.add_row(Text())
        if compact:
            grid.add_row(self._choice_line(choices, cursor))
        else:
            grid.add_row(self._chip_row(choices, cursor))
            grid.add_row(Text())
            grid.add_row(Text(choices[cursor].body, style=MUTED, justify="center"))
        docs_url = choices[cursor].docs_url
        if docs_url:
            grid.add_row(Text())
            grid.add_row(_docs_line(docs_url, width))
        return grid

    def _choice_line(self, choices: list[_Choice], cursor: int) -> Text:
        """Compact one-line choice: ``▸ Add      Skip``."""
        line = Text(justify="center")
        for i, choice in enumerate(choices):
            if i:
                line.append("      ")
            if i == cursor:
                line.append(f"▸ {choice.title}", style=f"bold {ACCENT}")
            else:
                line.append(f"  {choice.title}", style=MUTED)
        return line

    def _chip_row(self, choices: list[_Choice], cursor: int) -> Text:
        """Pill row for 2-3 option selects; focused chip highlighted."""
        line = Text(justify="center")
        for i, choice in enumerate(choices):
            if i:
                line.append("   ")
            if i == cursor:
                line.append(f" {choice.title} ", style=f"bold reverse {ACCENT}")
            else:
                line.append(f" {choice.title} ", style=MUTED)
        return line


def run_guided_selection(ui: GuidedSelectionUI) -> ProjectSelection:
    """Run the selection engine with esc/back support.

    Each pass replays the journal (instant, renders nothing) and goes live at
    the first unanswered screen. ``esc`` pops the last answer and restarts
    the pass; backing past the first question shows the welcome page again.
    Safe because the guided path is pure: state is rebuilt from answers
    alone, so every replay recomputes downstream effects with the one true
    rule set.
    """
    while True:
        ui.begin_pass()
        try:
            return run_project_selection(ui)
        except _GoBack:
            if not ui.pop_answer():
                # Backed past the first question: show the page that
                # precedes it (the preselected core stack).
                ui.show_core_stack()


def run_guided_init_flow(
    project_name: str,
    python_version: str,
    *,
    yes: bool = False,
    ui: GuidedSelectionUI | None = None,
    builder: Callable[[BuildPlan, _GuidedBuildReporter], object] | None = None,
    replay_command: Callable[[BuildPlan], str] | None = None,
    blueprint: Blueprint | None = None,
) -> tuple[BuildPlan, bool]:
    """The complete guided experience: welcome, questions, REVIEW, build, DONE.

    Returns the confirmed :class:`BuildPlan` plus the skip-llm-sync flag.
    The REVIEW screen replaces the terminal config dump and the ``[Y/n]``
    confirm — and because selection is journaled, ``esc`` on review steps
    back into the questions (the answer being revised re-focused), with the
    plan re-resolved on the way back. ``yes`` skips the review.

    When ``builder`` is given, the build runs INSIDE the experience: a
    building screen is shown, the builder's stdout/stderr are captured
    (terminal prints would corrupt the alternate screen), and the DONE
    screen closes the loop. Build failures raise
    :class:`GuidedBuildError` carrying the captured log, so the caller can
    print it to persistent scrollback after teardown.

    ``blueprint`` preselects a preset (``--blueprint <slug>``), skipping
    the starting-point screen: naming a slug on the command line IS the
    choice. Otherwise the screen asks.

    ``ui`` is injectable for scripted tests; the default opens the
    alternate screen for the duration.
    """
    own_ui = ui if ui is not None else GuidedSelectionUI(project_name)
    with own_ui:
        own_ui.show_welcome()
        # Starting point: blank canvas or a blueprint (esc returns to the
        # welcome page). A blueprint only seeds the answers — the pass below
        # journals them and lands on REVIEW with everything revisable.
        plan: BuildPlan | None = None
        while plan is None:
            if blueprint is None:
                while True:
                    try:
                        blueprint = own_ui.choose_blueprint()
                        break
                    except _GoBack:
                        own_ui.show_welcome()
            if blueprint is not None:
                own_ui.set_blueprint(blueprint)
            else:
                # The foundation page orients someone about to assemble a
                # stack question by question. A blueprint user is not
                # assembling one, so it would just be a page between them
                # and their build.
                own_ui.show_core_stack()
            while True:
                state: ProjectSelection = run_guided_selection(own_ui)
                candidate = resolve_build_plan(
                    project_name,
                    state.components,
                    state.scheduler_backend,
                    state.services,
                    python_version,
                )
                if yes or own_ui.show_review(candidate) == "build":
                    plan = candidate
                    break
                if own_ui.blueprint is not None:
                    # esc on a blueprint's review: the only decision made
                    # was the blueprint itself, so undo THAT and ask the
                    # starting point again. Stepping into the questions
                    # would drop them into a trail of answers they never
                    # gave.
                    own_ui.reset_selection()
                    blueprint = None
                    break
                own_ui.pop_answer()

        if builder is not None:
            import io
            from contextlib import redirect_stderr, redirect_stdout

            own_ui.show_building(plan)
            reporter = own_ui.build_reporter(plan)
            buffer = io.StringIO()
            try:
                with redirect_stdout(buffer), redirect_stderr(buffer):
                    project_path = builder(plan, reporter)
            except BaseException as exc:
                raise GuidedBuildError(buffer.getvalue()) from exc
            replay = replay_command(plan) if replay_command is not None else None
            own_ui.show_done(
                plan,
                project_path,
                replay,
                project_map=_capture_project_map(project_path),
            )
    return plan, get_skip_llm_sync_selection()


def _capture_project_map(project_path: object) -> str:
    """The post-gen project tree, as plain text for the DONE card.

    ``render_project_map`` prints line-by-line via typer; capturing it
    (click emits no ANSI on a non-tty stream) reuses the exact same map
    quick mode prints, without refactoring the printer. Best-effort: any
    failure just means the card omits the tree.
    """
    import io
    from contextlib import redirect_stdout
    from pathlib import Path as _Path

    try:
        path = _Path(str(project_path))
        if not path.exists():
            return ""
        from ..core.project_map import render_project_map

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            render_project_map(path)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 — the tree is decoration, never fatal
        return ""
