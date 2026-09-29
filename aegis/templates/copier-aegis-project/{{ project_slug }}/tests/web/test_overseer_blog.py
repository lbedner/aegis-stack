"""The Overseer Blog page: the Flet blog modal's tabs in Pulse's shape.

Overview counts, a posts list filtered by status with publish and archive
on each row, an editor that creates and edits posts, and the tags. Every
change goes through ``BlogService`` on the request's session.
"""

from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.blog", reason="no blog service in this stack")

from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import location, one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/blog"
PARTIALS = "/partials/overseer/blog"
BLOG = ComponentStatus(name="blog", message="Blog ready")


@pytest.fixture
def blog(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in, on the test's own session: rows vanish with the test."""
    sign_in(app, monkeypatch, status_with(services=[BLOG]))
    return async_client_with_db


def _get(client: TestClient, section: str = "", query: str = "") -> str:
    url = PAGE + (f"/{section}" if section else "") + (f"?{query}" if query else "")
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.text


def _create(
    client: TestClient, title: str, tags: str = "", content: str = "Hello"
) -> int:
    response = client.post(
        f"{PARTIALS}/posts", data={"title": title, "tags": tags, "content": content}
    )
    assert response.status_code == 200, response.text
    path = location(response)
    return int(parse_qs(urlparse(path).query)["post"][0])


def _rows(html: str) -> dict[str, str]:
    return {
        text(select(row, "td")[0]): text(row)
        for row in select(html, "#blog-posts tbody tr")
    }


def test_sections(blog: TestClient) -> None:
    assert [text(a) for a in select(_get(blog), "#overseer-subnav nav a")] == [
        "Overview",
        "Posts",
        "Tags",
    ]


def test_a_new_post_starts_as_a_draft(blog: TestClient) -> None:
    _create(blog, "Hello world")
    assert "Draft" in _rows(_get(blog, "posts"))["Hello world"]


def test_publishing_and_archiving_move_a_post_along(blog: TestClient) -> None:
    post = _create(blog, "Launch notes")
    assert blog.post(f"{PARTIALS}/posts/{post}/publish").status_code == 200
    assert "Published" in _rows(_get(blog, "posts"))["Launch notes"]
    assert blog.post(f"{PARTIALS}/posts/{post}/archive").status_code == 200
    assert "Archived" in _rows(_get(blog, "posts"))["Launch notes"]


def test_the_status_chips_filter_the_list(blog: TestClient) -> None:
    _create(blog, "Still a draft")
    live = _create(blog, "Already live")
    blog.post(f"{PARTIALS}/posts/{live}/publish")
    assert list(_rows(_get(blog, "posts", "status=draft"))) == ["Still a draft"]
    assert list(_rows(_get(blog, "posts", "status=published"))) == ["Already live"]


def _drawer(client: TestClient, post: int | str) -> str:
    response = client.get(f"{PARTIALS}/posts/{post}/drawer")
    assert response.status_code == 200, response.text
    return response.text


def test_a_row_opens_its_post_in_the_drawer(blog: TestClient) -> None:
    post = _create(blog, "Open me")
    link = one(_get(blog, "posts", "status=draft"), "#blog-posts tbody a")
    assert f"post={post}" in link.get("href") and "status=draft" in link.get("href")
    sync = one(_get(blog, "posts", f"post={post}"), "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/posts/{post}/drawer"


def test_a_new_post_opens_an_empty_editor(blog: TestClient) -> None:
    sync = one(_get(blog, "posts", "post=new"), "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/posts/new/drawer"
    html = _drawer(blog, "new")
    assert one(html, "input[name=title]").get("value") in (None, "")
    assert select(html, "input[name=slug]")


def test_the_editor_saves_to_its_post(blog: TestClient) -> None:
    """New posts create, open posts save: the form's target, not a name."""
    post = _create(blog, "Target")
    assert one(_drawer(blog, "new"), "form").get("hx-post") == f"{PARTIALS}/posts"
    assert one(_drawer(blog, post), "form").get("hx-post") == f"{PARTIALS}/posts/{post}"


def test_the_editor_opens_a_post_with_its_values(blog: TestClient) -> None:
    post = _create(blog, "Edit me", tags="release-notes python", content="Body text")
    html = _drawer(blog, post)
    assert one(html, "input[name=title]").get("value") == "Edit me"
    assert "Body text" in text(one(html, "textarea[name=content]"))
    assert one(html, "input[name=tags]").get("value") == "python, release-notes"
    assert not select(html, "input[name=slug]")  # the slug is the URL; fixed once made


def test_saving_the_editor_updates_the_post(blog: TestClient) -> None:
    post = _create(blog, "Old title")
    response = blog.post(
        f"{PARTIALS}/posts/{post}",
        data={"title": "New title", "tags": "", "content": "x"},
    )
    assert response.status_code == 200
    assert "New title" in _rows(_get(blog, "posts"))


def test_a_post_needs_a_title(blog: TestClient) -> None:
    response = blog.post(f"{PARTIALS}/posts", data={"title": "", "content": "x"})
    assert "HX-Location" not in response.headers
    assert triggers(response)["toast"]["tone"] == "error"
    assert _rows(_get(blog, "posts")) == {}


def test_tags_typed_in_the_editor_become_tags(blog: TestClient) -> None:
    _create(blog, "Tagged", tags="python release-notes")
    rows = select(_get(blog, "tags"), "#blog-tags tbody tr")
    assert [text(select(r, "td")[0]) for r in rows] == ["python", "release-notes"]


def test_a_tag_can_be_added_and_deleted(blog: TestClient) -> None:
    assert (
        blog.post(f"{PARTIALS}/tags", data={"name": "Announcements"}).status_code == 200
    )
    html = _get(blog, "tags")
    assert "Announcements" in text(one(html, "#blog-tags"))
    tag_id = (
        one(html, "#blog-tags [hx-get*='/confirm-delete']").get("hx-get").split("/")[-2]
    )
    assert blog.delete(f"{PARTIALS}/tags/{tag_id}").status_code == 204
    assert "Announcements" not in text(one(_get(blog, "tags"), "#blog-tags"))


def test_the_overview_counts_posts_by_status(blog: TestClient) -> None:
    _create(blog, "One")
    live = _create(blog, "Two")
    blog.post(f"{PARTIALS}/posts/{live}/publish")
    figures = {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(_get(blog), "#blog-figures > div")
    }
    assert figures["Posts"] == "2"
    assert figures["Drafts"] == "1"
    assert figures["Published"] == "1"
