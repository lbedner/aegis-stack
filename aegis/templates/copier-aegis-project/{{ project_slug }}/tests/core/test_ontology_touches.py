"""What a change touches, read from the system model: the parts owning its
files, the parts that depend on those, and the tables, routes, jobs and
worker tasks its files define."""

from app.core.ontology import touches
from app.core.ontology.model import (
    Category,
    Edge,
    EdgeKind,
    JobNode,
    Kind,
    ObjectNode,
    PartNode,
    RouteNode,
    TaskNode,
)
from tests._ontology import model_of

BACKEND = PartNode(kind=Kind.COMPONENT, name="backend", category=Category.COMPUTE)
DATABASE = PartNode(kind=Kind.COMPONENT, name="database", category=Category.DATA)
PAYMENT = PartNode(kind=Kind.SERVICE, name="payment", category=Category.APP)
CHARGES = PartNode(
    kind=Kind.SERVICE, name="payment.charges", category=Category.APP, owner=PAYMENT.id
)
BLOG = PartNode(kind=Kind.SERVICE, name="blog", category=Category.APP)
CHARGE = ObjectNode(
    name="payment_charge", module="app.services.payment.models", owner=PAYMENT.id
)
REFUND = RouteNode(
    name="POST /payment/refund",
    method="POST",
    path="/payment/refund",
    module="app.components.backend.api.payment.router",
    owner=PAYMENT.id,
)
SETTLE = JobNode(
    name="settle_job",
    schedule="cron hour=3",
    module="app.services.payment.jobs",
    owner=PAYMENT.id,
)
SETTLING = TaskNode(
    name="settle_job",
    queue="system",
    module="app.services.payment.jobs",
    owner=PAYMENT.id,
)
MODEL = model_of(
    [BACKEND, DATABASE, PAYMENT, CHARGES, BLOG, CHARGE, REFUND, SETTLE, SETTLING],
    [
        Edge(source=BACKEND.id, target=DATABASE.id, kind=EdgeKind.DEPENDS_ON),
        Edge(source=BLOG.id, target=PAYMENT.id, kind=EdgeKind.CALLS),
        Edge(source=PAYMENT.id, target=CHARGES.id, kind=EdgeKind.CONTAINS),
        Edge(source=PAYMENT.id, target=DATABASE.id, kind=EdgeKind.DEPENDS_ON),
    ],
)
OWNERS = {
    "app.services.payment.domains.charges.refunds": CHARGES.id,
    "app.services.payment.models": PAYMENT.id,
    "app.components.backend.api.payment.router": PAYMENT.id,
    "app.core.db": DATABASE.id,
}


def _touched(*paths: str) -> touches.Touched:
    return touches.touched(MODEL, paths, OWNERS.get)


def test_a_change_names_its_parts_what_depends_on_them_and_its_tables() -> None:
    found = _touched(
        "app/services/payment/domains/charges/refunds.py",
        "aegis/templates/copier-aegis-project/{{ project_slug }}"
        "/app/services/payment/models.py.jinja",
        "docs/payment.md",
    )
    assert found.parts == (PAYMENT.id, CHARGES.id)
    # Blog calls payment, which holds charges: a change to either is blog's.
    assert found.dependents == (BLOG.id,)
    assert found.tables == (CHARGE.id,)
    assert found.routes == found.jobs == ()
    assert found.elsewhere == ("docs/payment.md",)


def test_a_component_change_reaches_every_part_depending_on_it() -> None:
    found = _touched("app/core/db.py", "app/components/backend/api/payment/router.py")
    assert found.parts == (DATABASE.id, PAYMENT.id)
    assert found.dependents == (BACKEND.id, BLOG.id)
    assert found.routes == (REFUND.id,)


def test_the_summary_says_each_part_and_what_depends_on_it() -> None:
    summary = touches.summary(_touched("app/services/payment/models.py"))
    assert "`service:payment`" in summary
    assert "`service:blog`" in summary
    assert "`object:payment_charge`" in summary


def test_a_jobs_module_names_its_job_and_the_task_running_it() -> None:
    found = _touched("app/services/payment/jobs.py")
    assert (found.jobs, found.tasks) == ((SETTLE.id,), (SETTLING.id,))
