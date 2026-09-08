"""A short, visible demonstration of the ledger's concurrency guarantees."""

import asyncio
import time
from decimal import Decimal

from psycopg import AsyncConnection

from app.config import settings
from app.models import AccountCreate, TransferCreate
from app.service import create_account, reconcile, transfer

TRANSFER_COUNT = 20


async def post(request: TransferCreate) -> dict:
    async with await AsyncConnection.connect(settings.database_url) as conn:
        return await transfer(conn, request)


async def balances(account_ids: list) -> dict:
    async with await AsyncConnection.connect(settings.database_url) as conn:
        cursor = await conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ANY(%s) ORDER BY id",
            (account_ids,),
        )
        return dict(await cursor.fetchall())


async def main() -> None:
    run_id = time.time_ns()
    async with await AsyncConnection.connect(settings.database_url) as conn:
        alice = await create_account(
            conn,
            AccountCreate(name=f"demo-alice-{run_id}", currency="USD", opening_balance="1000.00"),
        )
        bob = await create_account(
            conn,
            AccountCreate(name=f"demo-bob-{run_id}", currency="USD", opening_balance="1000.00"),
        )

    account_ids = [alice["id"], bob["id"]]
    before = await balances(account_ids)
    requests = []
    for index in range(TRANSFER_COUNT):
        source, target = (alice, bob) if index % 2 == 0 else (bob, alice)
        requests.append(
            TransferCreate(
                from_account_id=source["id"],
                to_account_id=target["id"],
                amount=Decimal("10.00"),
                currency="USD",
                idempotency_key=f"demo-{run_id}-{index}",
            )
        )

    submitted = [post(request) for request in requests]
    submitted.extend(post(request) for request in requests[::5])
    responses = await asyncio.gather(*submitted)
    after = await balances(account_ids)

    async with await AsyncConnection.connect(settings.database_url) as conn:
        report = await reconcile(conn)

    initial_total = sum(before.values())
    final_total = sum(after.values())
    replayed = sum(response["replayed"] for response in responses)

    print("\nTRANSACTIONAL LEDGER — CONCURRENCY DEMO")
    print("=" * 39)
    print(f"Initial balances       Alice={before[alice['id']]}  Bob={before[bob['id']]}")
    print(f"Logical transfers      {TRANSFER_COUNT} opposing transfers")
    print(f"Requests submitted     {len(responses)} ({len(responses) - TRANSFER_COUNT} retries)")
    print(f"Idempotent replays     {replayed}")
    print(f"Final balances         Alice={after[alice['id']]}  Bob={after[bob['id']]}")
    print(f"Total before / after   {initial_total} / {final_total}")
    print(f"Money created or lost  {final_total - initial_total}")
    print(f"Ledger reconciliation {'PASS' if report['balanced'] else 'FAIL'}")
    print("=" * 39)

    assert replayed == len(responses) - TRANSFER_COUNT
    assert final_total == initial_total
    assert report["balanced"]


if __name__ == "__main__":
    asyncio.run(main())

