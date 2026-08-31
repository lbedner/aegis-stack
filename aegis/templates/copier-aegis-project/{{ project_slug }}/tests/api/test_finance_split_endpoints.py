"""The split endpoints: carve a transaction into lines, and read them back.

Same harness as ``test_finance_endpoints.py``: the mounted router end to
end through ``authenticated_client``, rows seeded owner-scoped with
``acting_owner_user_id``.
"""

from datetime import date

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService


async def _seeded_target_run(
    db: AsyncSession, owner: int | None
) -> tuple[int, int, int]:
    """(transaction_id, shopping_id, food_id) - a $76 categorized purchase."""
    service = FinanceService(db)
    shopping = await service.get_or_create_category_from_hint("Shopping")
    food = await service.get_or_create_category_from_hint("Food:Groceries")
    account = await service.create_manual_account(
        owner_user_id=owner,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )
    txn = await service.create_transaction(
        account_id=account.id,
        amount=-7_600,
        txn_date=date(2026, 8, 15),
        owner_user_id=owner,
        name="Target",
        category_id=shopping.id,
    )
    await db.commit()
    return txn.id, shopping.id, food.id


@pytest.mark.asyncio
async def test_split_endpoint_creates_lines_and_fills_the_difference(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    txn_id, shopping_id, food_id = await _seeded_target_run(
        async_db_session, acting_owner_user_id
    )

    response = authenticated_client.post(
        f"/api/v1/finance/transactions/{txn_id}/split",
        json={"parts": [{"amount": 2_500, "category_id": food_id}]},
    )

    assert response.status_code == 200
    lines = response.json()["items"]
    assert [(line["amount"], line["category_id"]) for line in lines] == [
        (-2_500, food_id),
        (-5_100, shopping_id),
    ]
    assert [line["category"] for line in lines] == ["Food:Groceries", "Shopping"]


@pytest.mark.asyncio
async def test_register_rows_carry_their_split_lines(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    txn_id, _, food_id = await _seeded_target_run(
        async_db_session, acting_owner_user_id
    )
    authenticated_client.post(
        f"/api/v1/finance/transactions/{txn_id}/split",
        json={"parts": [{"amount": 2_500, "category_id": food_id, "memo": "food"}]},
    )

    response = authenticated_client.get("/api/v1/finance/transactions")

    assert response.status_code == 200
    (row,) = response.json()["items"]
    assert row["is_split"] is True
    assert row["amount"] == -7_600
    assert [s["amount"] for s in row["splits"]] == [-2_500, -5_100]
    assert row["splits"][0]["category"] == "Food:Groceries"
    assert row["splits"][0]["memo"] == "food"


@pytest.mark.asyncio
async def test_unsplit_endpoint_removes_the_lines(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    txn_id, _, food_id = await _seeded_target_run(
        async_db_session, acting_owner_user_id
    )
    authenticated_client.post(
        f"/api/v1/finance/transactions/{txn_id}/split",
        json={"parts": [{"amount": 2_500, "category_id": food_id}]},
    )

    response = authenticated_client.delete(
        f"/api/v1/finance/transactions/{txn_id}/split"
    )

    assert response.status_code == 200
    assert response.json()["removed"] == 2
    rows = authenticated_client.get("/api/v1/finance/transactions").json()["items"]
    assert rows[0]["is_split"] is False
    assert rows[0]["splits"] == []


@pytest.mark.asyncio
async def test_bad_split_requests_are_rejected(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    txn_id, _, food_id = await _seeded_target_run(
        async_db_session, acting_owner_user_id
    )

    overflow = authenticated_client.post(
        f"/api/v1/finance/transactions/{txn_id}/split",
        json={"parts": [{"amount": 9_999_999, "category_id": food_id}]},
    )
    missing = authenticated_client.post(
        "/api/v1/finance/transactions/999999/split",
        json={"parts": [{"amount": 100, "category_id": food_id}]},
    )

    assert overflow.status_code == 400
    assert "exceed" in overflow.json()["detail"]
    assert missing.status_code == 404
