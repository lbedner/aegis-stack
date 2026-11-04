"""A page that declares what an agent may do on it, for the tests of page
actions (``app.core.pages``): two parts, one with an action of its own."""

from pydantic import BaseModel

from app.core.pages import Page, PageAction, PageTarget


class Stack(BaseModel):
    components: list[str]


LANDING = Page(
    (
        PageTarget(
            "build",
            "Compose a stack",
            (PageAction("compose", "Lay a stack out in the builder", Stack),),
        ),
        PageTarget("docs", "Where the docs start"),
    )
)
