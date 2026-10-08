"""A route's request, read from its OpenAPI operation: the fields a form
shows, and the request a filled-in form makes. Overseer's Routes sends it
once (Execute), its load tests many times, so both agree about a route."""

import asyncio
from enum import Enum

from fastapi import FastAPI
from pydantic import BaseModel
import pytest

from app.services.load_test.api import request_form


class Colour(str, Enum):
    RED = "red"
    BLUE = "blue"


class NewItem(BaseModel):
    name: str
    price: float = 9.5
    tags: list[str] = []


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}", summary="One item")
    async def read_item(
        item_id: int, q: str | None = None, colour: Colour = Colour.RED
    ) -> dict:
        return {"item_id": item_id, "q": q, "colour": colour}

    @app.post("/items")
    async def create_item(item: NewItem) -> NewItem:
        return item

    return app


def _op(method: str, path: str) -> request_form.Operation:
    op = request_form.operation(_app().routes, method, path)
    assert op is not None
    return op


def test_a_routes_parameters_come_from_its_schema() -> None:
    op = _op("GET", "/items/{item_id}")
    by_name = {p.name: p for p in op.params}

    assert op.summary == "One item"
    assert by_name["item_id"].location == "path" and by_name["item_id"].required
    assert by_name["item_id"].kind == "integer"
    assert by_name["q"].location == "query" and not by_name["q"].required
    assert by_name["colour"].choices == ["red", "blue"]
    assert by_name["colour"].default == "red"


def test_a_body_is_offered_as_an_example_built_from_its_model() -> None:
    op = _op("POST", "/items")

    assert op.body_required
    assert op.body_example == {
        "name": "string",
        "price": 9.5,
        "tags": [],
    }  # its defaults


def test_an_unknown_route_has_no_operation() -> None:
    assert request_form.operation(_app().routes, "GET", "/nope") is None


def test_a_filled_form_makes_its_request() -> None:
    op = _op("GET", "/items/{item_id}")

    built = request_form.build(
        op, {"path.item_id": "5", "query.q": "hi", "query.colour": ""}
    )

    assert built.url == "/items/5?q=hi"
    assert built.path_params == {"item_id": "5"} and built.payload is None


@pytest.mark.parametrize(
    "form, why",
    [
        ({}, "item_id"),
        ({"path.item_id": "five"}, "whole number"),
    ],
)
def test_a_form_that_cannot_make_a_request_says_why(
    form: dict[str, str], why: str
) -> None:
    with pytest.raises(ValueError, match=why):
        request_form.build(_op("GET", "/items/{item_id}"), form)


def test_a_write_is_sent_only_once_confirmed() -> None:
    op = _op("POST", "/items")
    body = '{"name": "pen"}'

    with pytest.raises(ValueError, match="changes data"):
        request_form.build(op, {"body": body})
    built = request_form.build(op, {"body": body, "confirm": "on"})

    assert built.payload == {"name": "pen"}


def test_a_body_that_is_not_json_says_so() -> None:
    with pytest.raises(ValueError, match="not JSON"):
        request_form.build(_op("POST", "/items"), {"body": "{nope", "confirm": "on"})


def test_execute_sends_it_once_and_shows_what_came_back() -> None:
    app = _app()
    op = request_form.operation(app.routes, "POST", "/items")
    assert op is not None
    built = request_form.build(op, {"body": '{"name": "pen"}', "confirm": "on"})

    answer = asyncio.run(
        request_form.execute(built, app, {"Authorization": "Bearer t"})
    )

    assert answer.status == 200
    assert '"name": "pen"' in answer.body and answer.ms >= 0
    assert answer.curl.startswith("curl -X POST") and "/items" in answer.curl
    assert "Authorization: Bearer" in answer.curl and '"name": "pen"' in answer.curl
