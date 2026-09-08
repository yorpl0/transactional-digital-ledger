"""Concurrent correctness test: simultaneous transfers and duplicate retries."""

import asyncio
import json
import os
import statistics
import time
from decimal import Decimal
from pathlib import Path

from psycopg import AsyncConnection

from app.models import AccountCreate, TransferCreate
from app.service import create_account, reconcile, transfer

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ledger:ledger@db:5432/ledger")
CONCURRENCY = 20
semaphore = asyncio.Semaphore(CONCURRENCY)


async def one_transfer(source, target, key: str) -> float:
    started = time.perf_counter()
    async with semaphore:
        async with await AsyncConnection.connect(DATABASE_URL) as conn:
            await transfer(
                conn,
                TransferCreate(
                    from_account_id=source,
                    to_account_id=target,
                    amount=Decimal("1.00"),
                    currency="USD",
                    idempotency_key=key,
                ),
            )
    return (time.perf_counter() - started) * 1000


async def run_stress(accounts: list[dict], operations: int) -> dict:
    requests = []
    for index in range(operations):
        source = accounts[index % len(accounts)]
        target = accounts[(index + 1) % len(accounts)]
        if index % 2:
            source, target = target, source
        key = f"stress-{time.time_ns()}-{index}"
        requests.append(one_transfer(source["id"], target["id"], key))
        if index % 10 == 0:
            requests.append(one_transfer(source["id"], target["id"], key))
    started = time.perf_counter()
    latencies = await asyncio.gather(*requests)
    elapsed = time.perf_counter() - started
    return {
        "logical_transfers": operations,
        "concurrency": CONCURRENCY,
        "requests_including_duplicates": len(requests),
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(len(requests) / elapsed, 1),
        "latency_ms_p50": round(statistics.median(latencies), 2),
        "latency_ms_p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
    }


async def main() -> None:
    async with await AsyncConnection.connect(DATABASE_URL) as conn:
        accounts = [
            await create_account(
                conn,
                AccountCreate(
                    name=f"stress-{time.time_ns()}-{i}",
                    currency="USD",
                    opening_balance=Decimal("1000.00"),
                ),
            )
            for i in range(10)
        ]
        initial = sum(account["balance"] for account in accounts)

    stress = await run_stress(accounts, 100)

    async with await AsyncConnection.connect(DATABASE_URL) as conn:
        cursor = await conn.execute(
            "SELECT SUM(balance) FROM accounts WHERE id = ANY(%s)",
            ([account["id"] for account in accounts],),
        )
        final = (await cursor.fetchone())[0]
        report = await reconcile(conn)
    assert final == initial, f"money changed: initial={initial}, final={final}"
    assert report["balanced"], report["mismatches"]
    result = {
        "correctness": {
            "initial_total": str(initial),
            "final_total": str(final),
            "money_created_or_lost": str(final - initial),
            "reconciliation_balanced": report["balanced"],
        },
        "stress_run": stress,
    }
    Path("benchmark-results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

