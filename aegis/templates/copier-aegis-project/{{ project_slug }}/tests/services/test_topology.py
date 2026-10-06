"""The stack's shape, as Overseer's Map draws it (``topology``): what runs
as its own process, in tiers (the edge, the app, its data), the connections
between them, and everything that runs inside the webserver instead."""

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
        ("worker", "cache"),
        ("worker", "database"),
    ]
    assert ("ingress", "backend") not in found.links


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
