"""The parts a line of a call names: by the names each is said by, strict,
so talk that only uses a part's ordinary word stays plain."""

from app.core.ontology.model import ExternalNode, Kind, PartNode, PartOption
from app.core.parts import Category
from app.services.meetings.domains.actions.heard import heard

NODES = (
    PartNode(kind=Kind.COMPONENT, name="scheduler", category=Category.COMPUTE),
    PartNode(kind=Kind.COMPONENT, name="cache", category=Category.DATA),
    PartNode(
        kind=Kind.COMPONENT,
        name="worker",
        category=Category.COMPUTE,
        options=(
            PartOption(
                name="backend",
                mode="single",
                choices=("arq", "taskiq", "dramatiq"),
                chosen="arq",
            ),
        ),
    ),
    PartNode(kind=Kind.SERVICE, name="finance", category=Category.APP),
    PartNode(kind=Kind.SERVICE, name="finance.ledger", category=Category.APP),
    ExternalNode(name="Plaid"),
)


def test_a_line_names_the_parts_it_says_each_once_in_order() -> None:
    hears = heard(NODES)

    found = hears.named("Redis went down, so the scheduler and Redis both stalled.")

    assert found == [("component:cache", "Redis"), ("component:scheduler", "Scheduler")]


def test_an_ordinary_word_is_a_part_only_by_its_full_name() -> None:
    hears = heard(NODES)

    assert hears.named("We should talk finance and hire another worker.") == []
    assert hears.named("The finance service syncs from Plaid.") == [
        ("service:finance", "Finance service"),
        ("external:Plaid", "Plaid"),
    ]


def test_a_part_is_heard_by_the_tool_this_stack_runs_it_on() -> None:
    hears = heard(NODES)

    assert hears.named("arq dropped a job") == [("component:worker", "Arq")]
    assert hears.named("Taskiq would not have") == []


def test_a_name_is_a_whole_word_and_any_case() -> None:
    hears = heard(NODES)

    assert hears.named("The rediscovery went fine.") == []
    assert hears.named("THE WORKER is stuck") == [("component:worker", "Worker")]
    # Its case folds to no name: talk, not a part.
    assert hears.named("REDİS is down") == []


def test_a_part_the_stack_lacks_is_never_heard() -> None:
    hears = heard(NODES)

    assert hears.named("Is the deploy agent up?") == []
    assert hears.ids == {
        "component:scheduler",
        "component:cache",
        "component:worker",
        "service:finance",
        "external:Plaid",
    }
