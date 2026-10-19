"""A route's dry path (``dry_path``): every hop it can take, read from the
code without sending a request, each at its line; where the walk cannot
see further, a stop at that line saying why."""

import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
import pytest

from app.core import source_index
from app.services.system import dry_path
from app.services.system.dry_path import DryPath, Entry, Need
from tests._files import write_tree

ROUTER = "app/components/backend/api/blog/router.py"
FILES = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/storage.py": (
        'FRONTS = "storage"\n'
        "class Storage:\n"
        "    def get(self, key: str) -> bytes:\n"
        "        return b''\n"
        "def get_storage() -> Storage:\n"
        "    return Storage()\n"
        "def make_storage():\n"
        "    return Storage()\n"
    ),
    "app/services/__init__.py": "",
    "app/services/blog/__init__.py": "",
    "app/services/blog/models.py": (
        "from sqlmodel import SQLModel\n"
        "class Post(SQLModel, table=True):\n"
        '    __tablename__ = "blog_post"\n'
    ),
    "app/services/blog/service.py": (
        "from sqlmodel import select\n"
        "from sqlmodel.ext.asyncio.session import AsyncSession\n"
        "from app.services.blog.models import Post\n"
        "class BlogService:\n"
        "    def __init__(self, db: AsyncSession) -> None:\n"
        "        self.db = db\n"
        "    async def get_post(self, slug: str) -> Post | None:\n"
        "        return await self._find(slug)\n"
        "    async def _find(self, slug: str) -> Post | None:\n"
        "        query = select(Post).where(Post.slug == slug)\n"
        "        return (await self.db.exec(query)).first()\n"
        "    async def save(self, title: str) -> None:\n"
        "        post = Post(title=title)\n"
        "        self.db.add(post)\n"
    ),
    "app/services/blog/deps.py": (
        "from app.services.blog.service import BlogService\n"
        "async def get_blog_service() -> BlogService:\n"
        "    return BlogService(None)\n"
    ),
    "app/services/blog/dry_jobs.py": (
        "async def dry_work(n: int) -> None:\n    return None\n"
    ),
    "app/services/blog/dry_checks.py": (
        "async def check_a() -> None:\n"
        "    return None\n"
        "async def check_b() -> None:\n"
        "    return None\n"
        'CHECKS = {"a": check_a, "b": check_b}\n'
        "async def run_checks() -> None:\n"
        "    for name, check in CHECKS.items():\n"
        "        await check()\n"
    ),
    "app/services/blog/mail/__init__.py": "",
    "app/services/blog/mail/keys.py": "SECRETS = ()\n",
    "app/services/blog/mail/client.py": "def send() -> None:\n    return None\n",
    "app/components/__init__.py": "",
    "app/components/worker/__init__.py": "",
    "app/components/worker/tasks/__init__.py": "",
    "app/components/worker/tasks/dry_tasks.py": (
        "async def dry_named_task(ctx: dict, n: int) -> None:\n"
        "    from app.services.blog.service import BlogService\n"
        "    service = BlogService(None)\n"
        '    await service.save("queued")\n'
    ),
    "app/components/backend/__init__.py": "",
    "app/components/backend/api/__init__.py": "",
    "app/components/backend/api/blog/__init__.py": "",
    ROUTER: (
        "from fastapi import Depends\n"
        "from app.core.storage import get_storage, make_storage\n"
        "from app.services.blog import dry_checks, dry_jobs\n"
        "from app.services.blog.mail import client\n"
        "from app.services.blog.deps import get_blog_service\n"
        "from app.services.blog.service import BlogService\n"
        "async def get_post(\n"
        "    slug: str, service: BlogService = Depends(get_blog_service)\n"
        ") -> None:\n"
        "    return await service.get_post(slug)\n"
        "async def queue(background: bool, pool) -> None:\n"
        "    if background:\n"
        "        await dry_jobs.dry_work.kiq(1)\n"
        '    await pool.enqueue_job("dry_named_task", 1)\n'
        "async def read(key: str) -> bytes:\n"
        "    return get_storage().get(key)\n"
        "async def guess(key: str) -> bytes:\n"
        "    return make_storage().get(key)\n"
        "async def ping() -> None:\n"
        "    await dry_checks.run_checks()\n"
        "async def loop_a() -> None:\n"
        "    await loop_b()\n"
        "async def loop_b() -> None:\n"
        "    await loop_a()\n"
        "async def blind(fn, thing) -> None:\n"
        "    fn()\n"
        "    thing.go()\n"
        "async def notify() -> None:\n"
        "    client.send()\n"
    ),
}
API = "app.components.backend.api.blog.router"


@pytest.fixture
def index(tmp_path: Path) -> source_index.Index:
    write_tree(tmp_path, FILES)
    return source_index.at(tmp_path)


def line_of(path: str, text: str) -> int:
    """The first line of ``path`` in ``FILES`` with ``text`` in it."""
    return next(n for n, line in enumerate(FILES[path].splitlines(), 1) if text in line)


def walked(index: source_index.Index, handler: str, *needs: Need) -> DryPath:
    entry = Entry(route=f"GET /{handler}", handler=(API, handler), needs=needs)
    return dry_path.trace(entry, index, providers={})


def hops(found: DryPath) -> list[tuple[str, str, int]]:
    return [(h.kind, h.symbol, h.line) for h in found.hops]


def test_an_injected_service_is_followed_to_the_table_it_reads(
    index: source_index.Index,
) -> None:
    """The handler, the dependency that hands it the service, the service's
    method and its own (``self``), and the table its ``select`` names."""
    service = "app.services.blog.service"
    need = Need(
        ("app.services.blog.deps", "get_blog_service"),
        "service",
        (service, "BlogService"),
    )
    found = walked(index, "get_post", need)
    assert hops(found) == [
        ("handler", f"{API}.get_post", line_of(ROUTER, "async def get_post")),
        (
            "depends",
            "app.services.blog.deps.get_blog_service",
            line_of(ROUTER, "Depends(get_blog_service)"),
        ),
        (
            "calls",
            f"{service}.BlogService.get_post",
            line_of(ROUTER, "service.get_post"),
        ),
        (
            "calls",
            f"{service}.BlogService._find",
            line_of("app/services/blog/service.py", "self._find"),
        ),
        (
            "reads",
            "app.services.blog.models.Post",
            line_of("app/services/blog/service.py", "select(Post)"),
        ),
    ]
    assert found.hops[-1].node == "object:blog_post"
    assert ("service:blog", "object:blog_post", "reads") in {
        (e.source, e.target, e.kind) for e in found.edges
    }


def test_work_handed_to_the_queue_is_followed_into_the_task(
    index: source_index.Index,
) -> None:
    """A task's ``.kiq`` and a literal name handed to ``enqueue_job`` both
    enqueue it, and the walk carries on in the task, async; a hop under an
    ``if`` says so."""
    found = walked(index, "queue")
    enqueued = {h.symbol: h for h in found.hops if h.kind == "enqueues"}
    kiq = enqueued["app.services.blog.dry_jobs.dry_work"]
    assert kiq.line == line_of(ROUTER, ".kiq(") and kiq.guard == "background"
    named = enqueued["app.components.worker.tasks.dry_tasks.dry_named_task"]
    assert named.line == line_of(ROUTER, "enqueue_job") and named.guard is None
    assert {h.mode for h in enqueued.values()} == {"async"}
    writes = next(h for h in found.hops if h.kind == "writes")
    assert writes.node == "object:blog_post" and writes.mode == "async"
    assert not found.stops  # the untyped pool hands work off, not a stop


def test_a_core_client_is_its_component_typed_by_what_it_returns(
    index: source_index.Index,
) -> None:
    """``get_storage().get`` is the storage component once, typed by what
    ``get_storage`` says it returns; a factory that does not say is a stop."""
    found = walked(index, "read")
    line = line_of(ROUTER, "get_storage().get")
    assert [(h.kind, h.node, h.line) for h in found.hops[1:]] == [
        ("uses", "component:storage", line)
    ]
    assert not found.stops
    guessed = walked(index, "guess")
    assert [(s.reason, s.line) for s in guessed.stops] == [
        ("deep_chain", line_of(ROUTER, "make_storage().get"))
    ]


def test_a_loop_over_a_registry_fans_out_to_each_entry(
    index: source_index.Index,
) -> None:
    found = walked(index, "ping")
    called = [h.symbol.rpartition(".")[2] for h in found.hops if h.kind == "calls"]
    assert called == ["run_checks", "check_a", "check_b"]
    assert not found.stops


def test_a_call_cycle_ends(index: source_index.Index) -> None:
    found = walked(index, "loop_a")
    assert [h.symbol.rpartition(".")[2] for h in found.hops] == [
        "loop_a",
        "loop_b",
        "loop_a",
    ]


def test_what_cannot_be_seen_is_a_stop_at_its_line(
    index: source_index.Index,
) -> None:
    found = walked(index, "blind")
    assert [(s.reason, s.line, s.text) for s in found.stops] == [
        ("callable_value", line_of(ROUTER, "fn()"), "fn()"),
        ("untyped_parameter", line_of(ROUTER, "thing.go()"), "thing.go()"),
    ]


def test_code_beside_a_providers_keys_calls_it(
    index: source_index.Index,
) -> None:
    """The keys are declared in one module (``SECRETS``), read by a client
    beside it: reaching the package that holds them calls the provider."""
    entry = Entry(route="GET /notify", handler=(API, "notify"))
    found = dry_path.trace(
        entry, index, providers={"app.services.blog.mail": ["Resend"]}
    )
    assert ("calls", "external:Resend") in {(h.kind, h.node) for h in found.hops}


# The stack's own routes ----------------------------------------------------


def _route(app: FastAPI, method: str, path: str) -> APIRoute:
    found = next(
        (
            r
            for r in app.routes
            if isinstance(r, APIRoute) and r.path == path and method in r.methods
        ),
        None,
    )
    if found is None:
        pytest.skip(f"no {method} {path} in this stack")
    return found


def test_a_route_is_anchored_on_its_handler_and_what_fastapi_injects(
    app: FastAPI,
) -> None:
    entry = dry_path.anchor(_route(app, "GET", "/health/detailed"))
    assert entry.handler == ("app.components.backend.api.health", "detailed_health")
    assert ("app.components.backend.security.operator_auth", "require_operator") in {
        n.symbol for n in entry.needs
    }


def test_the_detailed_health_route_reaches_the_status_walk(app: FastAPI) -> None:
    found = dry_path.walk(_route(app, "GET", "/health/detailed"))
    called = {h.symbol for h in found.hops}
    assert {
        "app.services.system.health.get_system_status",
        "app.services.system.health._collect_system_status",
    } <= called


def test_a_blog_post_by_slug_reads_its_post_and_tags(app: FastAPI) -> None:
    found = dry_path.walk(_route(app, "GET", "/api/v1/blog/posts/{slug}"))
    assert {
        "app.services.blog.deps.get_blog_service",
        "app.services.blog.service.BlogService.get_public_post_by_slug",
        "app.services.blog.service.BlogService._get_post_by_slug",
        "app.services.blog.queries.tags_for_posts",
    } <= {h.symbol for h in found.hops}
    nodes = {h.node for h in found.hops}
    assert {
        "component:database",
        "object:blog_post",
        "object:blog_post_tag",
        "object:blog_tag",
    } <= nodes


def test_extracting_a_document_runs_here_or_on_the_worker(app: FastAPI) -> None:
    """Inline: the extraction, the store it reads from, and the vision
    reader handed in (a stop). In the background: the task, async, where
    a worker runs it; else the same extraction, in this process."""
    found = dry_path.walk(
        _route(app, "POST", "/api/v1/documents/{document_id}/extract")
    )
    by_symbol = {h.symbol: h for h in found.hops}
    inline = next(
        h
        for h in found.hops
        if h.symbol
        == "app.services.documents.domains.extraction.pages.extract_document"
    )
    assert inline.guard == "not background"
    # The store it reads from (a component on the map where the stack has one).
    assert any(h.kind == "uses" and ".storage." in h.symbol for h in found.hops)
    assert "callable_value" in {s.reason for s in found.stops}
    if importlib.util.find_spec("app.components.worker"):
        task = next(h for h in found.hops if h.kind == "enqueues")
        assert task.symbol.endswith(".extract_document_task")
        assert task.mode == "async"
    assert "app.services.documents.domains.extraction.jobs.run_extraction" in by_symbol


def test_a_function_its_engine_renamed_is_found_where_it_was_written() -> None:
    """taskiq renames a task's function; its code keeps the name it was
    written with."""
    import types

    from app.core.time import utcnow
    from app.services.system.dry_names import symbol_of

    renamed = types.FunctionType(utcnow.__code__, utcnow.__globals__)
    renamed.__qualname__ = "utcnow__taskiq_original"
    assert symbol_of(renamed) == ("app.core.time", "utcnow")


def test_a_library_function_keeps_its_own_name() -> None:
    """A library under the project (its ``.venv``) is not the project's
    code: it keeps the name it gives itself."""
    from app.services.system.dry_names import symbol_of

    assert symbol_of(FastAPI.get) == (FastAPI.__module__, "FastAPI.get")


def test_a_service_is_reached_past_the_handler(index: source_index.Index) -> None:
    """The Service step's question: a task importing its service where it
    uses it reaches one; a handler living in a service is not its own."""
    task = Entry("t", ("app.components.worker.tasks.dry_tasks", "dry_named_task"))
    job = Entry("j", ("app.services.blog.dry_jobs", "dry_work"))
    assert dry_path.reaches_service(task, index)
    assert not dry_path.reaches_service(Entry("r", (API, "read")), index)
    assert not dry_path.reaches_service(job, index)
    assert not dry_path.reaches_service(None)


def test_a_shared_instance_is_walked_into_its_class(tmp_path: Path) -> None:
    """One instance the routes share (``ai_service = AIService(settings)``
    in its own module): a call on it is a call of its class's method."""
    shared = "app/components/backend/api/blog/shared.py"
    write_tree(
        tmp_path,
        FILES
        | {
            shared: (
                "from app.services.blog.service import BlogService\n"
                "blog = BlogService(None)\n"
            ),
            "app/components/backend/api/blog/show.py": (
                "from app.components.backend.api.blog.shared import blog\n"
                "async def show(slug: str) -> None:\n"
                "    return await blog.get_post(slug)\n"
            ),
        },
    )
    entry = Entry("show", ("app.components.backend.api.blog.show", "show"))
    hops = dry_path.trace(entry, source_index.at(tmp_path), set()).hops
    assert "app.services.blog.service.BlogService.get_post" in {h.symbol for h in hops}
