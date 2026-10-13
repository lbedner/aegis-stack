"""The map opened up, for its tests: a Server with Auth and Secrets inside
it, Auth calling the Database (the model) and needing Stripe's key; and a
finding about Auth, for what it should fix."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_container
from app.core.ontology import calls
from app.core.ontology.model import Edge, EdgeKind
from app.services.system.models import ComponentStatus
from app.services.system.pattern_findings import Finding
from tests._fake_runtime import REDIS, FakeRuntime, use_runtime
from tests._ontology import model_of
from tests.web.overseer import sign_in, status_with

AUTH = ComponentStatus(name="auth", message="Ready", metadata={})


def zoomable(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A Server with Auth and Secrets inside it; Auth talks to the Database
    and Stripe, whose key is set unless a test says otherwise."""
    server = ComponentStatus(name="backend", message="FastAPI", metadata={})
    database = ComponentStatus(name="database", message="Connected", metadata={})
    keys = ComponentStatus(name="secrets", message="Stored", metadata={})
    sign_in(app, monkeypatch, status_with(server, database, keys, services=[AUTH]))
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    # Auth's code calls the Database (the model); it needs Stripe's key now.
    model = model_of(
        edges=[
            Edge(
                source="service:auth", target="component:database", kind=EdgeKind.CALLS
            )
        ]
    )
    monkeypatch.setattr(overseer_container, "current", lambda: model)
    monkeypatch.setattr(
        calls,
        "providers",
        lambda declared, folder=None: [("Stripe", "STRIPE_SECRET_KEY")]
        if folder == "auth"
        else [],
    )
    monkeypatch.setattr(calls, "provider_keys", lambda: {})
    return TestClient(app)


def finding_of(check: str, title: str, evidence: tuple[str, ...]) -> Finding:
    """An enforced finding about Auth, at ``evidence``."""
    return Finding(
        check=check,
        subject="service:auth",
        severity="error",
        title=title,
        why="Why it matters.",
        evidence=evidence,
        action="Fix it.",
        fingerprint="0",
    )
