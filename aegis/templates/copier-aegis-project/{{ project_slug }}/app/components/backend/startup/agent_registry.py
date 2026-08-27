"""Agent-registry seeding at startup."""


def seed_agent_registry() -> dict[str, int]:
    """Seed the agent registry (agents, memory modules, tool rows).

    Idempotent and additive: existing rows are never mutated, so a project
    whose agents were tuned from the dashboard keeps that tuning. Runs at
    startup because a grant is by NAME against a ``tool`` row - without the
    sync, an agent's tools resolve to nothing.
    """
    from app.core.db import db_session as get_db_session
    from app.services.ai.fixtures import load_agent_registry_fixtures

    with get_db_session() as session:
        return load_agent_registry_fixtures(session)
