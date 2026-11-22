"""``auth[guest]``: one shared guest account anyone may sign in to, a
session per visitor. The flag reaches the answers through every door
(``init``'s parser, ``add-service``'s variant answers, the router wiring)
and is off unless asked for."""

import pytest

from aegis.constants import AnswerKeys
from aegis.core.auth_service_parser import parse_auth_service_config
from aegis.core.option_spec import variant_answers
from aegis.core.plugins.composer import serialize_plugin_to_answer
from aegis.core.services import SERVICES
from aegis.core.template_generator import TemplateGenerator

GUEST_ROUTER = "app.components.backend.api.auth.guest"


@pytest.mark.parametrize(
    ("service", "guest"),
    [("auth", False), ("auth[guest]", True), ("auth[org,oauth,guest]", True)],
)
def test_init_reads_the_flag(service: str, guest: bool) -> None:
    assert parse_auth_service_config(service).guest is guest
    gen = TemplateGenerator(
        project_name="test", selected_components=[], selected_services=[service]
    )
    assert gen.get_template_context()[AnswerKeys.AUTH_GUEST] == (
        "yes" if guest else "no"
    )


def test_add_service_names_its_answer() -> None:
    assert variant_answers("auth[guest]", SERVICES["auth"]) == {
        AnswerKeys.AUTH_GUEST: True
    }


@pytest.mark.parametrize("on", [False, True])
def test_the_guest_router_is_wired_only_with_the_flag(on: bool) -> None:
    result = serialize_plugin_to_answer(
        SERVICES["auth"], project_answers={AnswerKeys.AUTH_GUEST: on}
    )
    modules = [r["module"] for r in result["wiring"]["routers"]]
    assert (GUEST_ROUTER in modules) is on
