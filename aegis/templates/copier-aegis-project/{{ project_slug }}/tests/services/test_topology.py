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
