"""What the app is, in brief (``ontology.summary``), and as the text an
agent always has (``text``): each part with what it is for, the tables by
owner with what each links to, and the changes that can be made."""

from app.core.ontology.model import (
    ChangeNode,
    Edge,
    EdgeKind,
    JobNode,
    Kind,
    ObjectNode,
    PartNode,
    PartOption,
    QueueNode,
    TaskNode,
)
from app.core.ontology.summary import summary, text
from app.core.parts import Category
from tests._ontology import model_of

BACKEND = PartNode(
    kind=Kind.COMPONENT,
    name="backend",
    category=Category.COMPUTE,
    description="The HTTP API",
)
PAYMENT = PartNode(kind=Kind.SERVICE, name="payment", category=Category.APP)
CHARGES = PartNode(
    kind=Kind.SERVICE, name="payment.charges", category=Category.APP, owner=PAYMENT.id
)
CHARGE = ObjectNode(name="payment_charge", class_name="Charge", owner=PAYMENT.id)
CUSTOMER = ObjectNode(name="payment_customer", class_name="Customer", owner=PAYMENT.id)
REFUND = ChangeNode(
    name="payment.refund", title="Refund a charge", object=CHARGE.id, owner=PAYMENT.id
)
MODEL = model_of(
    [BACKEND, PAYMENT, CHARGES, CHARGE, CUSTOMER, REFUND],
    [
        Edge(source=CHARGE.id, target=CUSTOMER.id, kind=EdgeKind.LINK, via=via)
        for via in ("customer_id", "billed_to_id")
    ],
)


def test_the_map_names_each_part_with_what_it_is_for() -> None:
    found = text(summary(MODEL))
    assert "component:backend: The HTTP API" in found
    assert "service:payment" in found


def test_the_map_says_how_each_part_is_built_and_what_else_it_could_be() -> None:
    """Asked about a worker library the stack does not run, the agent must
    already know it is one of the worker's choices, not outside the app."""
    worker = PartNode(
        kind=Kind.COMPONENT,
        name="worker",
        category=Category.COMPUTE,
        options=(
            PartOption(
                name="backend",
                mode="single",
                choices=("arq", "taskiq", "dramatiq"),
                chosen="taskiq",
            ),
            PartOption(name="rag", mode="flag", choices=("rag",), chosen=True),
            PartOption(name="voice", mode="flag", choices=("voice",), chosen=False),
        ),
    )
    found = text(summary(model_of([worker], [])))
    assert "backend taskiq (of arq, taskiq, dramatiq)" in found
    assert "rag on" in found and "voice off" in found


def test_the_map_lists_the_scheduled_jobs_with_when_and_whose() -> None:
    """Asked how the app is backed up, the agent must already know a
    backup job runs, not conclude from the parts that none does."""
    backup = JobNode(
        name="database_backup",
        schedule="trigger=cron hour=2 minute=0",
        owner="shared:system",
    )
    found = text(summary(model_of([BACKEND, backup], [])))
    assert "- database_backup (shared:system): trigger=cron hour=2 minute=0" in found


def test_the_map_lists_each_queue_with_its_tasks() -> None:
    """Asked what the load test queue runs, she drew the load test service:
    the map named it and no queue (2026-10-25)."""
    queue = QueueNode(name="load_test", owner="component:queue")
    tasks = [
        TaskNode(name=name, queue="load_test", owner="component:worker")
        for name in ("cpu_task", "io_task")
    ]
    found = text(summary(model_of([BACKEND, queue, *tasks], [])))
    assert "- queue:load_test: cpu_task, io_task" in found


def test_the_map_leaves_a_parts_pieces_to_the_tool() -> None:
    """A few hundred tokens: a service's sub-services are depth, as its
    routes are."""
    assert CHARGES.id not in text(summary(MODEL))
    assert CHARGES in summary(MODEL).parts  # the tool's summary keeps them


def test_a_table_linked_twice_to_another_names_it_once() -> None:
    assert summary(MODEL).tables[PAYMENT.id]["payment_charge"] == ["payment_customer"]


def test_the_map_lists_the_tables_by_owner_with_their_links() -> None:
    line = next(
        line for line in text(summary(MODEL)).splitlines() if "payment_charge" in line
    )
    assert line.startswith(f"- {PAYMENT.id}:")
    assert "payment_customer" in line.split("payment_charge", 1)[1]


def test_the_map_lists_the_changes_and_the_table_each_changes() -> None:
    line = next(
        line for line in text(summary(MODEL)).splitlines() if "payment.refund" in line
    )
    assert "Refund a charge" in line and "payment_charge" in line


def test_the_apps_data_alone_has_no_parts() -> None:
    """What anyone may read (``domain``): the tables and the changes, not
    the parts behind them."""
    found = text(summary(MODEL.domain()))
    assert "component:backend" not in found
    assert "payment_charge" in found and "payment.refund" in found


def test_the_map_says_where_it_ends() -> None:
    """With the map in hand she stopped calling the tool and filled in the
    rest from general knowledge (2026-10-16): an admin's map names what it
    lacks and the tool that has it. Anyone else's promises no route walk
    their tool refuses."""
    admin = text(summary(MODEL)).splitlines()[0]
    anyone = text(summary(MODEL.domain())).splitlines()[0]
    assert "routes" in admin and "ontology tool" in admin
    assert "route" not in anyone and "ontology tool" in anyone
