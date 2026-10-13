"""The walk behind a dry path (``dry_path``), and what it finds.

A hop is a call at its line: into a function (``calls``), a core client's
component (``uses``, by what it ``FRONTS``), a table a query names
(``reads``, ``writes``), work handed to the queue (``enqueues``, then the
task, async), or an outside provider whose keys the code holds. A hop
under an ``if`` carries the test, never evaluated."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.core.ontology.model import Kind, Mode, node_id
from app.core.ontology.parts import node_of
from app.core.source_functions import called
from app.core.source_index import Index, Module, Symbol
from app.core.source_members import Def

from .dry_names import SELF, Names, Scope

DEPTH = 12  # how many calls deep the walk goes
# Called with a task's name first: the queue's front doors (arq's own too).
ENQUEUES = frozenset({"enqueue_task", "enqueue_job"})
# Called on a task itself: taskiq's, dramatiq's.
HANDS_OFF = frozenset({"kiq", "send"})
# A table named in one of these is read, or written (``session.add(post)``).
READS = frozenset({"select", "select_from", "join", "outerjoin", "get"})
WRITES = frozenset({"insert", "update", "delete", "add", "merge"})
INJECTS = frozenset({"Depends", "Security"})
UNSEEN = "ORM lazy loads and cascades, text() SQL, middleware and events"


class HopKind(StrEnum):
    HANDLER = "handler"
    DEPENDS = "depends"
    CALLS = "calls"
    USES = "uses"
    READS = "reads"
    WRITES = "writes"
    ENQUEUES = "enqueues"


class Reason(StrEnum):
    UNTYPED_PARAMETER = "untyped_parameter"
    DEEP_CHAIN = "deep_chain"
    CALLABLE_VALUE = "callable_value"
    REGISTRY_KEY = "registry_key"
    DEPTH = "depth"


REASONS = {
    Reason.UNTYPED_PARAMETER: "A parameter with no type: the caller decides what it is",
    Reason.DEEP_CHAIN: "A chain past what the walk follows",
    Reason.CALLABLE_VALUE: "A function handed in as a value",
    Reason.REGISTRY_KEY: "Looked up by key in a registry the walk cannot read",
    Reason.DEPTH: f"More than {DEPTH} calls deep",
}


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Hop(Frozen):
    """A call at its line (the handler: its definition), and what it reaches."""

    id: int
    parent: int | None  # the hop whose code makes it
    kind: HopKind
    symbol: str  # what it reaches, dotted: a function, a table's class
    node: str | None  # ... as the model's node
    path: str
    line: int
    text: str
    guard: str | None = None  # the ``if`` it is under, as written
    mode: Mode = Mode.SYNC


class Stop(Frozen):
    parent: int
    reason: Reason
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Need:
    """A dependency FastAPI injects: what it calls, the parameter it fills
    and the class it hands over, and what it needs in turn."""

    symbol: Symbol
    param: str | None = None
    returns: Symbol | None = None
    needs: tuple[Need, ...] = ()


@dataclass(frozen=True)
class Entry:
    route: str
    handler: Symbol
    needs: tuple[Need, ...] = ()


class Walker:
    def __init__(
        self, index: Index, ids: set[str] | None, providers: Mapping[str, list[str]]
    ) -> None:
        self.index, self.ids, self.providers = index, ids, providers
        self.names = Names(index)
        self.hops: list[Hop] = []
        self.stops: list[Stop] = []
        self.seen: set[Symbol] = set()
        self.reached: set[str] = set()  # packages whose providers are drawn
        self.used: set[tuple[int, str, int]] = set()  # (parent, component, line)

    # Hops and stops ---------------------------------------------------------

    def _add(
        self,
        kind: HopKind,
        symbol: Symbol,
        node: str | None,
        line: int,
        scope: Scope,
        guard: str | None = None,
        *,
        parent: int | None = None,
        mode: Mode | None = None,
    ) -> int:
        """A hop at ``line`` of the scope's module, made by its code (by
        hop ``parent``, given one)."""
        self.hops.append(
            Hop(
                id=len(self.hops) + 1,
                parent=(scope.parent if parent is None else parent) or None,
                kind=kind,
                symbol=".".join(p for p in symbol if p),
                node=node,
                **asdict(scope.module.place(line)),
                guard=guard,
                mode=mode or scope.mode,
            )
        )
        return len(self.hops)

    def _stop(self, reason: Reason, line: int, scope: Scope) -> None:
        self.stops.append(
            Stop(parent=scope.parent, reason=reason, **asdict(scope.module.place(line)))
        )

    def _node(self, module: str) -> str | None:
        return node_of(module, self.index, self.ids)

    def _code(self, symbol: Symbol) -> tuple[Module, Def] | None:
        """The module and the function ``symbol`` names, if it is one."""
        module = self.index.get(symbol[0])
        found = self.names.source.definition(symbol)
        return (module, found) if module and isinstance(found, Def) else None

    # Entering code ------------------------------------------------------------

    def start(self, entry: Entry) -> None:
        if (code := self._code(entry.handler)) is None:
            return  # nothing on disk to walk
        module, handler = code
        node = self._node(module.name)
        root = self._add(
            HopKind.HANDLER, entry.handler, node, handler.lineno, Scope(module, 0)
        )
        self._inject(entry.needs, module, handler, root)
        self.enter(entry.handler, root, Mode.SYNC, 1, _given(entry.needs))

    def _inject(
        self, needs: tuple[Need, ...], user: Module, at: Def, parent: int
    ) -> None:
        """Each dependency of the code ``at``: a hop at its ``Depends(...)``
        (else its own definition), then what it needs, then its body."""
        for need in needs:
            if (code := self._code(need.symbol)) is None:
                continue  # a library's: FastAPI's own security schemes
            module, found = code
            line = self._injected_at(at, user, need.symbol)
            where = Scope(user, parent) if line else Scope(module, parent)
            node = self._node(module.name)
            hop = self._add(
                HopKind.DEPENDS, need.symbol, node, line or found.lineno, where
            )
            if module.declared.fronts:
                continue  # a core client: the component, not its internals
            self._inject(need.needs, module, found, hop)
            self.enter(need.symbol, hop, Mode.SYNC, 2, _given(need.needs))

    def _injected_at(self, at: Def, user: Module, symbol: Symbol) -> int | None:
        scope = Scope(user, 0)
        for node in ast.walk(at):
            if (
                isinstance(node, ast.Call)
                and called(node.func) in INJECTS
                and node.args
                and self.names.resolve(node.args[0], scope) == symbol
            ):
                return node.lineno
        return None

    def enter(
        self,
        symbol: Symbol,
        parent: int,
        mode: Mode,
        depth: int,
        given: Mapping[str, Symbol] | None = None,
    ) -> None:
        if symbol in self.seen:
            return
        self.seen.add(symbol)
        if (code := self._code(symbol)) is None:
            return
        module, found = code
        scope = Scope(module, parent, mode, depth)
        member = symbol[1] or ""
        if "." in member:
            scope.owner = (symbol[0], member.rpartition(".")[0])
        args = found.args
        for arg in args.posonlyargs + args.args + args.kwonlyargs:
            scope.params[arg.arg] = arg.annotation is not None
            if typed := self.names.source.typed(module.name, arg.annotation):
                scope.types[arg.arg] = typed
        scope.types |= given or {}
        self._locals(found, scope)
        for statement in found.body:
            self._visit(statement, scope, None)

    def _locals(self, found: Def, scope: Scope) -> None:
        """Each local given a project class: annotated, made by one, or
        returned by a function that says so."""
        for node in ast.walk(found):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target
                typed = self.names.source.typed(scope.module.name, node.annotation)
            elif (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                target = node.targets[0]
                typed = self.names.made(node.value, scope)
            else:
                continue
            if typed:
                scope.types[target.id] = typed

    def _visit(self, node: ast.AST, scope: Scope, guard: str | None) -> None:
        """Every call under ``node``, the ones in its arguments first."""
        if isinstance(node, ast.If):
            self._visit(node.test, scope, guard)
            test = ast.unparse(node.test)
            for child in node.body:
                self._visit(child, scope, test)
            for child in node.orelse:
                self._visit(child, scope, f"not {test}")
            return
        if isinstance(node, ast.For | ast.AsyncFor):
            self._registry(node, scope, guard)
        for child in ast.iter_child_nodes(node):
            self._visit(child, scope, guard)
        if isinstance(node, ast.Call):
            self._call(node, scope, guard)

    # Calls ------------------------------------------------------------------

    def _call(self, call: ast.Call, scope: Scope, guard: str | None) -> None:
        name = called(call.func)
        if task := self._handed_off(call, name, scope):
            node = self._node(task[0])
            hop = self._add(
                HopKind.ENQUEUES, task, node, call.lineno, scope, guard, mode=Mode.ASYNC
            )
            self.enter(task, hop, Mode.ASYNC, scope.depth + 1)
            return
        if name in READS or name in WRITES:
            kind = HopKind.READS if name in READS else HopKind.WRITES
            for arg in call.args:
                found = self.names.table(arg, scope)
                table = node_id(Kind.OBJECT, found[1]) if found else None
                if found and table and (self.ids is None or table in self.ids):
                    self._add(kind, found[0], table, call.lineno, scope, guard)
        target = self.names.resolve(call.func, scope)
        if target is None:
            self._unresolved(call, scope)
        elif self.names.is_function(target):
            self._reach(target, call.lineno, scope, guard)

    def _handed_off(
        self, call: ast.Call, name: str | None, scope: Scope
    ) -> Symbol | None:
        """The task a call queues: by its name (``enqueue_task("x", ...)``)
        or on the task (``x.kiq(...)``)."""
        first = call.args[0] if call.args else None
        if (
            name in ENQUEUES
            and isinstance(first, ast.Constant)
            and isinstance(first.value, str)
        ):
            return self.names.task(first.value)
        if name in HANDS_OFF and isinstance(call.func, ast.Attribute):
            task = self.names.resolve(call.func.value, scope)
            return task if self.names.is_function(task) else None
        return None

    def _reach(
        self, target: Symbol, line: int, scope: Scope, guard: str | None
    ) -> None:
        """A hop into ``target``: a core client's component, else the
        function, its outside providers, and its body."""
        module = self.index.get(target[0])
        if module and (fronts := module.declared.fronts):
            used = (scope.parent, fronts, line)  # ``get_storage().get``: once
            if used not in self.used:
                self.used.add(used)
                component = self._node(module.name)
                self._add(HopKind.USES, target, component, line, scope, guard)
            return
        hop = self._add(
            HopKind.CALLS, target, self._node(target[0]), line, scope, guard
        )
        package = target[0].rpartition(".")[0]
        if package not in self.reached:
            self.reached.add(package)
            for provider in self.providers.get(package, []):
                outside = node_id(Kind.EXTERNAL, provider)
                self._add(
                    HopKind.CALLS, target, outside, line, scope, guard, parent=hop
                )
        if target not in self.seen and scope.depth >= DEPTH:
            self._stop(Reason.DEPTH, line, scope)
            return
        self.enter(target, hop, scope.mode, scope.depth + 1)

    def _unresolved(self, call: ast.Call, scope: Scope) -> None:
        """Why a call goes nowhere the walk can follow, if the project's
        code could be behind it: else it is a library's, and not a stop."""
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in SELF:
                return  # ``cls(...)``: the class it is in, made
            if func.id in scope.unread:
                self._stop(Reason.REGISTRY_KEY, call.lineno, scope)
            elif func.id in scope.params and func.id not in scope.covered:
                self._stop(Reason.CALLABLE_VALUE, call.lineno, scope)
            return
        head = func.value if isinstance(func, ast.Attribute) else None
        if (
            isinstance(head, ast.Name)
            and scope.params.get(head.id) is False
            and head.id not in SELF
        ):
            self._stop(Reason.UNTYPED_PARAMETER, call.lineno, scope)
        elif (isinstance(head, ast.Call) and self.names.unsaid(head, scope)) or (
            isinstance(head, ast.Attribute) and self.names.resolve(head, scope)
        ):
            self._stop(Reason.DEEP_CHAIN, call.lineno, scope)

    def _registry(
        self, loop: ast.For | ast.AsyncFor, scope: Scope, guard: str | None
    ) -> None:
        """A loop over a top-level registry reaches each callable in it; one
        the walk cannot read leaves its names a stop where they are called."""
        symbol = self.names.registry(loop, scope)
        if symbol is None:
            return
        names = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
        entries = self.names.entries(symbol)
        if entries is None:
            scope.unread |= names
            return
        if entries:
            scope.covered |= names
        for entry in entries:
            self._reach(entry, loop.lineno, scope, guard)


def _given(needs: tuple[Need, ...]) -> dict[str, Symbol]:
    """The parameters FastAPI fills, each typed by what its dependency returns."""
    return {n.param: n.returns for n in needs if n.param and n.returns}
