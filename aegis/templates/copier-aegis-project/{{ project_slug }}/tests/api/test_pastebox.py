"""The pastebox: OS-clipboard images pasted anywhere on the dashboard.

Generic framework plumbing, deliberately not tied to any service: a
browser-side capture script (injected into the dashboard page) posts
pasted images to ``/api/v1/pastebox``; any consumer surface drains the
staged images and decides what they mean (chat attaches them to the
next message). The box is instance-wide and drain-once: whichever open
consumer drains first owns the paste.
"""

import base64

from fastapi.testclient import TestClient

from app.components.backend.middleware.paste_capture import inject_paste_script
from app.core.pastebox import Pastebox

_PNG = b"\x89PNG fake bytes"


class TestPasteboxStore:
    def test_stage_and_drain_once(self) -> None:
        box = Pastebox()
        box.stage(media_type="image/png", data=_PNG, name="shot.png")

        drained = box.drain()

        assert [(i["media_type"], i["name"]) for i in drained] == [
            ("image/png", "shot.png")
        ]
        assert base64.b64decode(drained[0]["data_b64"]) == _PNG
        assert box.drain() == []

    def test_the_box_keeps_only_the_newest(self) -> None:
        box = Pastebox(max_items=2)
        for n in ("a.png", "b.png", "c.png"):
            box.stage(media_type="image/png", data=_PNG, name=n)

        assert [i["name"] for i in box.drain()] == ["b.png", "c.png"]

    def test_incoming_marks_count_until_the_upload_stages(self) -> None:
        """The "receiving" indicator's source of truth: the capture
        script pings before uploading, and staging consumes the mark."""
        box = Pastebox()
        box.mark_incoming()
        box.mark_incoming()
        assert box.incoming() == 2

        box.stage(media_type="image/png", data=_PNG, name="a.png")
        assert box.incoming() == 1

    def test_stale_incoming_marks_expire(self) -> None:
        """A failed upload must not pin the indicator forever."""
        clock = [100.0]
        box = Pastebox(now=lambda: clock[0])
        box.mark_incoming()
        assert box.incoming() == 1

        clock[0] += 30.0
        assert box.incoming() == 0


class TestPasteboxEndpoints:
    def test_paste_then_drain_roundtrip(self, client: TestClient) -> None:
        posted = client.post(
            "/api/v1/pastebox",
            files={"file": ("pasted.png", _PNG, "image/png")},
        )
        assert posted.status_code == 200
        assert posted.json()["staged"] == 1

        drained = client.post("/api/v1/pastebox/drain")
        assert drained.status_code == 200
        (item,) = drained.json()["items"]
        assert item["media_type"] == "image/png"
        assert item["name"] == "pasted.png"
        assert base64.b64decode(item["data_b64"]) == _PNG

        assert client.post("/api/v1/pastebox/drain").json()["items"] == []

    def test_incoming_ping_shows_up_in_drain_until_staged(
        self, client: TestClient
    ) -> None:
        assert client.post("/api/v1/pastebox/incoming").status_code == 200

        first = client.post("/api/v1/pastebox/drain").json()
        assert first["incoming"] == 1

        client.post(
            "/api/v1/pastebox",
            files={"file": ("pasted.png", _PNG, "image/png")},
        )
        second = client.post("/api/v1/pastebox/drain").json()
        assert second["incoming"] == 0
        assert [i["name"] for i in second["items"]] == ["pasted.png"]

    def test_non_images_are_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/pastebox",
            files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 415


class TestPasteScriptInjection:
    def test_script_lands_before_closing_head(self) -> None:
        html = b"<html><head><title>x</title></head><body></body></html>"

        patched = inject_paste_script(html)

        assert b"navigator" not in html  # untouched input
        assert patched.index(b"<script>") < patched.index(b"</head>")
        assert b"/api/v1/pastebox" in patched

    def test_html_without_head_is_left_alone(self) -> None:
        blob = b'{"not": "html"}'
        assert inject_paste_script(blob) == blob
