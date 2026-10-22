"""The map opened up, for its tests: a Server with Auth and Secrets inside
it, Auth calling the Database (the model) and needing Stripe's key; and a
finding about Auth, for what it should fix."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_container, overseer_zoom
from app.core.ontology import calls
from app.core.ontology.model import Edge, EdgeKind
from app.services.system import kept_requests, service_pieces
from app.services.system.models import ComponentStatus
from app.services.system.pattern_findings import Finding
from app.services.system.service_pieces import Piece
from tests._fake_runtime import REDIS, FakeRuntime, use_runtime
from tests._ontology import model_of
from tests.web.overseer import sign_in, status_with

AUTH = ComponentStatus(name="auth", message="Ready", metadata={})
# Auth opened up: four pieces, and what each imports.
ROUTER = "app.components.backend.api.auth.router"
PIECES = [
    Piece(
        "piece:router",
        "Router",
        "entry",
        (ROUTER,),
        ("app/components/backend/api/auth/router.py",),
    ),
    Piece(
        "piece:facade",
        "Facade",
        "facade",
        ("app.services.auth.service",),
        ("app/services/auth/service.py",),
    ),
    Piece(
        "piece:queries",
        "Queries",
        "data",
        ("app.services.auth.queries",),
        ("app/services/auth/queries.py",),
    ),
    Piece(
        "piece:health",
        "Health",
        "probe",
        ("app.services.auth.health",),
        ("app/services/auth/health.py",),
    ),
]
DB = "component:database"
LINES = {
    # Past the facade to data (red); to the Server it lives in (no line);
    # the database, used by every piece: a rail.
    "piece:router": ["piece:facade", "piece:queries", "component:backend", DB],
    "piece:facade": ["piece:queries", DB],
    "piece:queries": ["piece:facade", DB],  # back a lane (amber)
    "piece:health": ["piece:router", DB],  # a probe: no lines
}


def zoomable(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, *more: ComponentStatus
) -> TestClient:
    """A Server with Auth and Secrets inside it (and ``more`` beside it);
    Auth talks to the Database and Stripe, whose key is set unless a test
    says otherwise."""
    server = ComponentStatus(name="backend", message="FastAPI", metadata={})
    database = ComponentStatus(name="database", message="Connected", metadata={})
    keys = ComponentStatus(name="secrets", message="Stored", metadata={})
    found = status_with(server, database, keys, *more, services=[AUTH])
    sign_in(app, monkeypatch, found)
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
    monkeypatch.setattr(kept_requests, "current", lambda: model)
    monkeypatch.setattr(
        calls,
        "providers",
        lambda declared, folder=None: [("Stripe", "STRIPE_SECRET_KEY")]
        if folder == "auth"
        else [],
    )
    monkeypatch.setattr(calls, "provider_keys", lambda: {})
    return TestClient(app)


def auth_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth opens up into ``PIECES``; nothing else does."""
    monkeypatch.setattr(
        overseer_zoom,
        "pieces_of",
        lambda subject, model: (PIECES, LINES)
        if subject == "service:auth"
        else ([], {}),
    )
    monkeypatch.setattr(
        service_pieces,
        "held",
        lambda subject: PIECES if subject == "service:auth" else [],
    )


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
