"""``optional``: a part of the stack where it is rendered, else None;
``present``: whether it is, without importing it."""

from app.core.discovery import optional, present


def test_a_part_the_stack_has_is_given() -> None:
    assert optional("app.core.discovery", "optional") is optional


def test_a_part_whose_service_is_missing_is_none() -> None:
    """A stack without the service has no package to look inside: that is
    "not here" too, never an error (a meetings stack asking for speech)."""
    assert optional("app.services.no_such_service.domains.voice") is None
    assert optional("app.core.no_such_module") is None


def test_present_answers_without_importing() -> None:
    assert present("app.core.discovery")
    assert not present("app.services.no_such_service")
    assert not present("app.services.no_such_service.domains.voice")
