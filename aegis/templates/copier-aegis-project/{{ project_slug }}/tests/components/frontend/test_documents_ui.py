"""The Documents card and modal, minus the runtime.

Only the pure edges: what a row shows for its date, what the search box
matches, and that the card renders the counts the health check hands it.
"""

from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.theme import AegisTheme as Theme
from app.components.frontend.dashboard.cards.documents_card import DocumentsCard
from app.components.frontend.dashboard.modals.documents_activity import (
    activity_rows,
)
from app.components.frontend.dashboard.modals.documents_detail_pane import (
    replaces_options,
)
from app.components.frontend.dashboard.modals.documents_modal import (
    display_date,
    matching_documents,
)
from app.components.frontend.dashboard.modals.documents_pages import (
    extraction_summary,
)
from app.services.documents.health import DOCUMENTS_MODAL_ID
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests.components.frontend._tree import texts


def test_display_date_prefers_the_documents_own_date() -> None:
    doc = {"document_date": "2026-08-27", "received_at": "2026-08-31T14:02:11"}
    assert display_date(doc) == "Aug 27, 2026"


def test_display_date_falls_back_to_when_it_arrived() -> None:
    doc = {"document_date": None, "received_at": "2026-08-31T14:02:11"}
    assert display_date(doc) == "Aug 31, 2026"


def test_search_matches_title_and_tags_not_storage_keys() -> None:
    docs = [
        {"title": "Renewal request", "tags": ["medicaid"], "storage_key": "sha256/ab"},
        {"title": "HVCU statement", "tags": [], "storage_key": "sha256/medicaid"},
    ]

    assert [d["title"] for d in matching_documents(docs, "medic")] == [
        "Renewal request"
    ]
    assert len(matching_documents(docs, "")) == 2


def test_card_shows_the_counts_the_health_check_reports() -> None:
    status = ComponentStatus(
        name="documents",
        status=ComponentStatusType.HEALTHY,
        message="47 documents",
        metadata={"total": 47, "this_month": 6, "bytes": 222_298_112},
    )

    card = DocumentsCard(status).build()
    shown = texts(card)

    # The card opens the modal registered under the same id: one constant.
    assert card.component_name == DOCUMENTS_MODAL_ID
    assert "47" in shown
    assert "6" in shown
    assert "212.0 MB" in shown


def test_replaces_options_offer_every_other_document_and_nothing() -> None:
    docs = [
        {"id": 1, "title": "POA draft"},
        {"id": 2, "title": "POA executed"},
        {"id": 3, "title": "Statement"},
    ]

    options = replaces_options(docs, current_id=2)

    assert options[0] == ("none", "Nothing")
    assert [label for _, label in options[1:]] == ["POA draft", "Statement"]
    assert all(key != "2" for key, _ in options)


def test_extraction_summary_reads_like_a_sentence() -> None:
    assert (
        extraction_summary({"read": 7, "unread": 0, "skipped": 0})
        == "7 pages extracted"
    )
    assert (
        extraction_summary({"read": 5, "unread": 2, "skipped": 0})
        == "5 of 7 pages extracted"
    )
    assert (
        extraction_summary({"read": 0, "unread": 0, "skipped": 3})
        == "Already extracted"
    )


def test_placeholders_save_as_no_value() -> None:
    from app.components.frontend.dashboard.modals.documents_detail_pane import _chosen

    assert _chosen("none") is None and _chosen("") is None and _chosen(None) is None
    assert _chosen("mail") == "mail"


def test_activity_rows_name_the_document_and_read_like_a_sentence() -> None:
    jobs = [
        {
            "job_id": "a",
            "name": "documents-extract:2",
            "status": "running",
            "label": "Reading page 3 of 10...",
        },
        {
            "job_id": "b",
            "name": "documents-extract:1",
            "status": "done",
            "result": {"read": 10, "unread": 0, "skipped": 0},
        },
        {
            "job_id": "c",
            "name": "documents-extract:7",
            "status": "failed",
            "error": "model not found",
        },
        {"job_id": "d", "name": "finance-import:x.csv", "status": "done", "result": {}},
    ]
    titles = {1: "Executed POA", 2: "Bedner J Request"}

    rows = activity_rows(jobs, titles)

    assert [r.title for r in rows] == ["Bedner J Request", "Executed POA", "Document 7"]
    assert rows[0].detail == "Reading page 3 of 10..." and rows[0].running
    assert rows[1].detail == "10 pages extracted" and not rows[1].running
    assert rows[2].detail == "model not found" and rows[2].failed


def test_a_job_queued_too_long_says_no_worker_has_picked_it_up() -> None:
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    fresh = datetime.now(UTC).isoformat()
    jobs = [
        {
            "job_id": "a",
            "name": "documents-extract:1",
            "status": "running",
            "label": "Queued...",
            "started_at": old,
        },
        {
            "job_id": "b",
            "name": "documents-extract:2",
            "status": "running",
            "label": "Queued...",
            "started_at": fresh,
        },
        {
            "job_id": "c",
            "name": "documents-extract:3",
            "status": "running",
            "label": "Reading page 2 of 5",
            "started_at": fresh,
        },
    ]

    by_id = {
        r.job_id: r for r in activity_rows(jobs, {1: "Old", 2: "New", 3: "Working"})
    }

    assert by_id["a"].detail == "Queued for 2m, no worker has picked it up"
    assert by_id["b"].detail == "Queued..."
    # A sweeping bar is the claim that work is under way. Only the job a
    # worker has actually reported progress on gets to make it.
    assert (by_id["a"].queued, by_id["a"].stalled) == (True, True)
    assert (by_id["b"].queued, by_id["b"].stalled) == (True, False)
    assert (by_id["c"].queued, by_id["c"].stalled) == (False, False)


def test_a_job_with_no_timestamp_is_still_only_queued() -> None:
    """Age unknown is not permission to animate."""
    jobs = [
        {
            "job_id": "a",
            "name": "documents-extract:1",
            "status": "running",
            "label": "Queued...",
            "started_at": "",
        },
    ]

    row = activity_rows(jobs, {1: "Old"})[0]

    assert row.queued is True
    assert row.stalled is False


def test_only_a_job_a_worker_took_shows_a_moving_bar() -> None:
    import flet as ft

    from app.components.frontend.dashboard.modals.documents_activity import (
        ActivityRow,
        ActivityTab,
    )
    from tests.components.frontend._tree import texts

    def bars(control: ft.Control) -> list[ft.ProgressBar]:
        found: list[ft.ProgressBar] = []
        stack = [control]
        while stack:
            node = stack.pop()
            if isinstance(node, ft.ProgressBar):
                found.append(node)
            stack.extend(getattr(node, "controls", None) or [])
            content = getattr(node, "content", None)
            if content is not None:
                stack.append(content)
        return found

    def row(*, queued: bool, stalled: bool) -> ActivityRow:
        return ActivityRow(
            job_id="a",
            document_id=1,
            title="Doc",
            detail="Queued...",
            running=True,
            failed=False,
            queued=queued,
            stalled=stalled,
            incomplete=False,
            when="just now",
            started_at="",
        )

    running_cell = ActivityTab._status_cell(row(queued=False, stalled=False))
    queued_cell = ActivityTab._status_cell(row(queued=True, stalled=False))
    stalled_cell = ActivityTab._status_cell(row(queued=True, stalled=True))

    assert bars(running_cell), "a job a worker took should show its bar"
    assert not bars(queued_cell)
    assert not bars(stalled_cell)
    assert "Queued" in texts(queued_cell)
    assert "Waiting" in texts(stalled_cell)
    # The running cell carries the worker's own words, so no second column
    # has to repeat them.
    working = row(queued=False, stalled=False)
    working.detail = "Reading page 2 of 5"
    assert "Reading page 2 of 5" in texts(ActivityTab._status_cell(working))


def test_a_row_says_when_it_ran() -> None:
    """Two runs of the same document are only tellable apart by time."""
    from datetime import UTC, datetime, timedelta

    from app.components.frontend.dashboard.modals.documents_activity import age_label

    now = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
    ago = lambda **kw: (now - timedelta(**kw)).isoformat()  # noqa: E731

    assert age_label(ago(seconds=5), now) == "just now"
    assert age_label(ago(minutes=4), now) == "4m ago"
    assert age_label(ago(hours=3), now) == "3h ago"
    assert age_label(ago(days=2), now) == "2d ago"
    # A record written before the store kept timestamps says nothing rather
    # than guessing.
    assert age_label("", now) == ""


def test_rows_carry_their_age_and_the_newest_is_first() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
    jobs = [
        {
            "job_id": "old",
            "name": "documents-extract:1",
            "status": "done",
            "result": {"read": 2},
            "started_at": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "job_id": "new",
            "name": "documents-extract:1",
            "status": "done",
            "result": {"read": 3},
            "started_at": (now - timedelta(minutes=1)).isoformat(),
        },
    ]

    rows = activity_rows(jobs, {1: "Doc"}, now=now)

    assert [r.job_id for r in rows] == ["new", "old"]
    assert [r.when for r in rows] == ["1m ago", "2h ago"]


def test_extract_is_offered_only_while_a_page_is_unread() -> None:
    """A run that did nothing is what "Already extracted" means. Do not
    offer that run."""
    from app.components.frontend.dashboard.modals.documents_pages import (
        has_unread_pages,
    )

    # Never extracted: no page rows yet, so there is everything to do.
    assert has_unread_pages([]) is True
    assert has_unread_pages([{"page_number": 1, "status": "unread"}]) is True
    assert (
        has_unread_pages(
            [
                {"page_number": 1, "status": "read"},
                {"page_number": 2, "status": "unread"},
            ]
        )
        is True
    )
    assert (
        has_unread_pages(
            [{"page_number": 1, "status": "read"}, {"page_number": 2, "status": "read"}]
        )
        is False
    )


def test_a_fully_read_document_offers_a_force_extract() -> None:
    """Re-reading is a deliberate act, not an accident.

    Plain Extract on a fully-read document does nothing, so the button
    turns into a force: the way to read every page again with whatever
    model is now in force.
    """
    from app.components.frontend.dashboard.modals.documents_detail_pane import (
        DocumentDetailPane,
    )

    pane = DocumentDetailPane.__new__(DocumentDetailPane)
    pane._extract_button = PulseButton(  # type: ignore[attr-defined]
        on_click_callable=lambda: None, text="Extract"
    )

    pane._sync_extract_state([{"page_number": 1, "status": "read"}])
    assert pane._extract_button.text == "Force extract"
    assert pane._force_extract is True
    assert "again" in (pane._extract_button.tooltip or "")
    assert pane._extract_button.disabled is False

    pane._sync_extract_state([{"page_number": 1, "status": "unread"}])
    assert pane._extract_button.text == "Extract"
    assert pane._force_extract is False
    assert not pane._extract_button.tooltip


def test_the_force_button_asks_the_api_to_force() -> None:
    import asyncio

    from app.components.frontend.dashboard.modals.documents_detail_pane import (
        DocumentDetailPane,
    )

    calls: list[str] = []

    class _Api:
        async def post(self, path: str) -> dict[str, str]:
            calls.append(path)
            return {"job_id": "j"}

    class _Page:
        """Enough page for a snackbar to land on."""

        def open(self, _control: object) -> None:
            return None

        def update(self) -> None:
            return None

    pane = DocumentDetailPane.__new__(DocumentDetailPane)
    pane._doc = {"id": 7, "title": "Doc"}  # type: ignore[attr-defined]
    pane._api = lambda: _Api()  # type: ignore[attr-defined]
    pane.page = _Page()  # type: ignore[attr-defined]
    pane._extract_button = PulseButton(  # type: ignore[attr-defined]
        on_click_callable=lambda: None, text="Extract"
    )

    pane._sync_extract_state([{"page_number": 1, "status": "read"}])
    asyncio.run(pane._extract())
    assert calls == ["/api/v1/documents/7/extract?background=true&force=true"]

    pane._sync_extract_state([{"page_number": 1, "status": "unread"}])
    asyncio.run(pane._extract())
    assert calls[-1] == "/api/v1/documents/7/extract?background=true"


def test_a_run_that_left_pages_unread_is_not_drawn_as_a_success() -> None:
    """Seven pages a model refused is not a green tick.

    The run finished, so it is not "failed" in the job's sense, but it did
    not do what it was asked and the table has to say so.
    """
    from app.components.frontend.dashboard.modals.documents_activity import (
        ActivityTab,
    )
    from tests.components.frontend._tree import texts

    jobs = [
        {
            "job_id": "none-read",
            "name": "documents-extract:1",
            "status": "done",
            "result": {"read": 0, "unread": 7},
            "started_at": "",
        },
        {
            "job_id": "some-read",
            "name": "documents-extract:2",
            "status": "done",
            "result": {"read": 5, "unread": 2},
            "started_at": "",
        },
        {
            "job_id": "all-read",
            "name": "documents-extract:3",
            "status": "done",
            "result": {"read": 3, "unread": 0},
            "started_at": "",
        },
    ]

    by_id = {r.job_id: r for r in activity_rows(jobs, {1: "A", 2: "B", 3: "C"})}

    assert by_id["none-read"].incomplete is True
    assert by_id["some-read"].incomplete is True
    assert by_id["all-read"].incomplete is False

    cell = ActivityTab._status_cell(by_id["none-read"])
    assert "0 of 7 pages extracted" in texts(cell)
    assert cell.color == Theme.Colors.WARNING
    assert ActivityTab._status_cell(by_id["all-read"]).color == Theme.Colors.ACCENT
