"""The Documents card and modal, minus the runtime.

Only the pure edges: what a row shows for its date, what the search box
matches, and that the card renders the counts the health check hands it.
"""

from app.components.frontend.dashboard.cards.documents_card import DocumentsCard
from app.components.frontend.dashboard.modals.documents_modal import (
    display_date,
    matching_documents,
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
