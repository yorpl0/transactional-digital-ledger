import asyncio
from decimal import Decimal

import pytest
from psycopg import AsyncConnection

from app.config import settings
from app.models import AccountCreate, TransferCreate
from app.service import create_account, reconcile, transfer

pytestmark = pytest.mark.integration


async def make_account(conn, name: str, balance: str):
    return await create_account(
        conn,
        AccountCreate(name=name, currency="USD", opening_balance=Decimal(balance)),
    )


@pytest.mark.asyncio
async def test_duplicate_transfer_posts_once(conn) -> None:
    source = await make_account(conn, "duplicate-source", "100.00")
    target = await make_account(conn, "duplicate-target", "0.00")
    request = TransferCreate(
        from_account_id=source["id"],
        to_account_id=target["id"],
        amount=Decimal("25.00"),
        currency="USD",
        idempotency_key=f"duplicate-{source['id']}",
    )
    first = await transfer(conn, request)
    second = await transfer(conn, request)
    assert first["id"] == second["id"]
    assert second["replayed"] is True

    balances = await conn.execute(
        "SELECT id, balance FROM accounts WHERE id = ANY(%s)",
        ([source["id"], target["id"]],),
    )
    assert dict(await balances.fetchall()) == {
        source["id"]: Decimal("75.00"),
        target["id"]: Decimal("25.00"),
    }


@pytest.mark.asyncio
async def test_opposite_transfers_do_not_deadlock(conn) -> None:
    left = await make_account(conn, "deadlock-left", "100.00")
    right = await make_account(conn, "deadlock-right", "100.00")

    async def run(request):
        async with await AsyncConnection.connect(settings.database_url) as separate:
            return await transfer(separate, request)

    await asyncio.wait_for(
        asyncio.gather(
            run(TransferCreate(from_account_id=left["id"], to_account_id=right["id"], amount=Decimal("10.00"), currency="USD", idempotency_key=f"left-{left['id']}")),
            run(TransferCreate(from_account_id=right["id"], to_account_id=left["id"], amount=Decimal("10.00"), currency="USD", idempotency_key=f"right-{right['id']}")),
        ),
        timeout=5,
    )
    report = await reconcile(conn)
    assert report["balanced"] is True

