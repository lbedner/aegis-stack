"""HTML to the words a person would read off it: one home for every
reader of somebody else's page (a mailed message, a page the assistant
fetched). Styles, scripts and the head are not words; block tags are
line breaks; entities come back as characters.
"""

from __future__ import annotations

from html.parser import HTMLParser

# Tags that end a line when flattened. A phone or an address on its own
# line is what the identity rules read; a <p> is a line.
BLOCKS = frozenset(
    {
        "p",
        "br",
        "div",
        "tr",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "td",
        "th",
        "table",
        "section",
        "article",
        "header",
        "footer",
        "blockquote",
        "pre",
        "dd",
        "dt",
        "dl",
        "ul",
        "ol",
    }
)
# Pieces of a page that are not its words.
QUIET = frozenset({"style", "script", "noscript", "svg", "head"})


class _Words(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.title: list[str] = []
        self.quiet = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in QUIET:
            self.quiet += 1
        if tag == "title":
            self.in_title = True
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in QUIET:
            self.quiet = max(0, self.quiet - 1)
        if tag == "title":
            self.in_title = False
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        elif not self.quiet:
            self.out.append(data)


def page_text(html: str) -> tuple[str, str]:
    """A page's title and its readable text: one line per block, spaces
    folded, blank lines dropped."""
    words = _Words()
    words.feed(html)
    lines = (" ".join(line.split()) for line in "".join(words.out).splitlines())
    return " ".join("".join(words.title).split()), "\n".join(
        line for line in lines if line
    )


def flatten(html: str) -> str:
    """The readable text alone."""
    return page_text(html)[1]
