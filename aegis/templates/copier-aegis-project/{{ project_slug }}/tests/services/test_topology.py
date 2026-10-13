"""The stack's shape, as Overseer's Map draws it (``topology``): what runs
as its own process, in tiers (the edge, the app, its data), the connections
between them, and everything that runs inside the webserver instead."""

from app.core import ownership
from app.core.constants import ComponentName
from app.services.system import topology


def test_its_own_processes_sit_in_tiers_and_the_rest_in_the_webserver() -> None:
    found = topology.shape(
        [
            "backend",
            "web_frontend",
            "database",
            "worker",
            "cache",
            "ingress",
            "auth",
            "ai",
        ]
    )
    assert found.tiers == [["ingress"], ["backend", "worker"], ["database", "cache"]]
    assert found.hosted == ["web_frontend", "auth", "ai"]


def test_a_connection_is_drawn_only_when_both_ends_are_there() -> None:
    found = topology.shape(["backend", "database", "worker", "cache"])
    assert found.links == [
        ("backend", "database"),
        ("backend", "cache"),
        ("worker", "database"),
    ]
    assert ("ingress", "backend") not in found.links


def test_the_queue_sits_with_the_data_and_takes_all_the_work() -> None:
    """The worker's queue, in Redis beside the Cache: the Server and the
    Scheduler hand work to it, the Worker takes work from it."""
    found = topology.shape(
        ["backend", "scheduler", "worker", "database", topology.QUEUE, "cache"]
    )
    assert found.tiers[-1] == ["database", topology.QUEUE, "cache"]
    into = {a for a, b in found.links if b == topology.QUEUE}
    assert into == {"backend", "scheduler", "worker"}
    assert not {("worker", "cache"), ("scheduler", "cache")} & set(found.links)


def test_the_flow_runs_from_who_enqueues_through_the_queue_to_the_worker() -> None:
    """Work's way through the stack, left to right: the worker takes from
    the queue, so the queue sits between who hands work over and the worker,
    and what they all reach comes last."""
    c = ComponentName
    found = topology.flow(
        [c.INGRESS, c.BACKEND, c.SCHEDULER, c.WORKER, c.DATABASE, topology.QUEUE]
    )
    assert [set(tier) for tier in found.tiers] == [
        {c.INGRESS},
        {c.BACKEND, c.SCHEDULER},
        {topology.QUEUE},
        {c.WORKER},
        {c.DATABASE},
    ]
    assert (topology.QUEUE, c.WORKER) in found.links
    assert (c.WORKER, topology.QUEUE) not in found.links


def test_a_line_either_side_of_the_queue_is_queued_work() -> None:
    """Handed to the queue, or taken from it: never waited on."""
    assert topology.queued(ComponentName.BACKEND, topology.QUEUE)
    assert topology.queued(topology.QUEUE, ComponentName.WORKER)
    assert not topology.queued(ComponentName.BACKEND, ComponentName.DATABASE)


def test_a_failing_part_names_the_failing_parts_it_depends_on_at_the_root() -> None:
    """The Database down takes the Server with it, and the Ingress in front
    of the Server: both point at the Database, not at each other."""
    causes = topology.causes({"ingress", "backend", "database", "cache"} - {"cache"})
    assert causes == {"backend": ["database"], "ingress": ["database"]}


def test_a_failing_part_with_no_failing_dependency_is_its_own_cause() -> None:
    assert topology.causes({"ingress"}) == {}
    assert topology.causes({"database"}) == {}


def test_the_server_zoomed_in_puts_callers_above_what_they_call() -> None:
    """Documents calls AI, which calls RAG: three tiers, then everything
    they reach outside the server."""
    links = {
        "service_documents": ["service_ai", "storage"],
        "service_ai": ["service_rag", "database", "outside:Anthropic"],
        "service_rag": [],
        "service_auth": ["database"],
    }
    found = topology.zoomed(list(links), links)
    assert [set(tier) for tier in found.tiers] == [
        {"service_documents"},
        {"service_ai"},
        {"service_rag", "service_auth"},
        {"database", "storage", "outside:Anthropic"},
    ]
    assert ("service_ai", "outside:Anthropic") in found.links


def test_causes_follow_the_links_they_are_given() -> None:
    links = [("service_payment", "service_comms"), ("service_comms", "outside:Resend")]
    assert topology.causes({"service_payment", "service_comms"}, links) == {
        "service_payment": ["service_comms"]
    }


def test_each_tier_sits_under_what_reaches_it() -> None:
    """A node takes the average place of the nodes linking to it, so
    lines run down rather than across: the Database under Auth on the
    left, Stripe under Payment on the right."""
    links = {
        "service_auth": ["database"],
        "service_blog": [],
        "service_payment": ["outside:Stripe"],
    }
    found = topology.zoomed(list(links), links)
    assert found.tiers[-1] == ["database", "outside:Stripe"]
    flipped = topology.zoomed(
        ["service_payment", "service_blog", "service_auth"], links
    )
    assert flipped.tiers[-1] == ["outside:Stripe", "database"]


# Every part the map can place, and the hosted ones it cannot.
EVERY = (
    "ingress",
    "backend",
    "worker",
    "scheduler",
    "database",
    "queue",
    "cache",
    "storage",
    "ollama",
    "browser",
    "web_frontend",
    "frontend",
    "mcp",
    "secrets",
    "observability",
)


def test_the_full_stack_is_drawn_as_it_always_was() -> None:
    """Pinned before the tiers and lines moved into the parts' own specs."""
    found = topology.shape(list(EVERY))
    assert found.tiers == [
        ["ingress"],
        ["backend", "worker", "scheduler"],
        ["database", "queue", "cache", "storage", "ollama", "browser"],
    ]
    assert found.links == [
        ("ingress", "backend"),
        ("backend", "database"),
        ("backend", "queue"),
        ("backend", "cache"),
        ("backend", "storage"),
        ("backend", "ollama"),
        ("backend", "browser"),
        ("worker", "queue"),
        ("worker", "database"),
        ("scheduler", "database"),
        ("scheduler", "queue"),
    ]
    assert found.hosted == [
        "web_frontend",
        "frontend",
        "mcp",
        "secrets",
        "observability",
    ]


def test_the_full_stacks_flow_is_as_it_always_was() -> None:
    found = topology.flow(list(EVERY))
    assert found.tiers == [
        ["ingress"],
        ["backend", "scheduler"],
        ["queue"],
        ["worker"],
        ["cache", "storage", "ollama", "browser", "database"],
    ]
    assert ("queue", "worker") in found.links and ("worker", "queue") not in found.links


def test_each_parts_shape_and_keys_are_as_they_always_were() -> None:
    assert {k: str(v) for k, v in topology.ROLES.items()} == {
        "database": "store",
        "cache": "store",
        "queue": "queue",
        "storage": "bucket",
    }
    assert (topology.KEYS, ownership.HOST) == ("secrets", "backend")


def test_causes_end_on_a_cycle() -> None:
    """Two services importing each other (a seed loader can) both failing:
    each is the other's cause, and the walk ends."""
    found = topology.causes({"ai", "finance"}, [("ai", "finance"), ("finance", "ai")])
    assert found == {"ai": ["finance"], "finance": ["ai"]}
