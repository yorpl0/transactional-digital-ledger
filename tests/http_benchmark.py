"""HTTP benchmark for the real transfer endpoint, with an optional saturation run."""

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")
QUICK_LEVELS = (1, 5, 10, 20, 40)
FULL_LEVELS = (1, 5, 10, 20, 40, 80, 120, 160)
SHARDED_ACCOUNT_PAIRS = 10


def percentile(values: list[float], percentile_value: float) -> float:
    index = max(0, int(len(values) * percentile_value) - 1)
    return values[index]


async def create_account(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post(
        "/accounts",
        json={"name": name, "currency": "USD", "opening_balance": "10000.00"},
    )
    response.raise_for_status()
    return response.json()["id"]


def select_accounts(accounts: list[str], workload: str, index: int) -> tuple[str, str]:
    pair_index = 0 if workload == "hot" else index % SHARDED_ACCOUNT_PAIRS
    source, target = accounts[pair_index * 2 : pair_index * 2 + 2]
    if (index // max(1, SHARDED_ACCOUNT_PAIRS)) % 2:
        source, target = target, source
    return source, target


async def run_trial(
    client: httpx.AsyncClient,
    accounts: list[str],
    workload: str,
    concurrency: int,
    request_count: int,
    trial_id: str,
) -> tuple[list[float], Counter, float]:
    semaphore = asyncio.Semaphore(concurrency)

    async def send(index: int) -> tuple[float, int]:
        source, target = select_accounts(accounts, workload, index)
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await client.post(
                    "/transfers",
                    json={
                        "from_account_id": source,
                        "to_account_id": target,
                        "amount": "1.00",
                        "currency": "USD",
                        "idempotency_key": f"http-bench-{trial_id}-{index}",
                    },
                )
                status = response.status_code
            except httpx.HTTPError:
                status = 0
            latency = (time.perf_counter() - started) * 1000
        return latency, status

    started = time.perf_counter()
    outcomes = await asyncio.gather(*(send(index) for index in range(request_count)))
    elapsed = time.perf_counter() - started
    return (
        [latency for latency, _ in outcomes],
        Counter(status for _, status in outcomes),
        elapsed,
    )


async def run_level(
    client: httpx.AsyncClient,
    accounts: list[str],
    workload: str,
    concurrency: int,
    request_count: int,
    repetitions: int,
    run_id: int,
) -> dict:
    all_latencies: list[float] = []
    status_counts: Counter = Counter()
    total_elapsed = 0.0
    for repetition in range(repetitions):
        latencies, statuses, elapsed = await run_trial(
            client,
            accounts,
            workload,
            concurrency,
            request_count,
            f"{run_id}-{workload}-{concurrency}-{repetition}",
        )
        all_latencies.extend(latencies)
        status_counts.update(statuses)
        total_elapsed += elapsed

    all_latencies.sort()
    total_requests = request_count * repetitions
    errors = total_requests - status_counts[201]
    return {
        "concurrency": concurrency,
        "requests": total_requests,
        "repetitions": repetitions,
        "requests_per_second": round(total_requests / total_elapsed, 1),
        "latency_ms_p50": round(statistics.median(all_latencies), 2),
        "latency_ms_p95": round(percentile(all_latencies, 0.95), 2),
        "latency_ms_p99": round(percentile(all_latencies, 0.99), 2),
        "latency_ms_max": round(max(all_latencies), 2),
        "errors": errors,
        "status_counts": dict(sorted(status_counts.items())),
    }


def summarize(results: list[dict]) -> dict:
    peak = max(results, key=lambda result: result["requests_per_second"])
    error_free = [result for result in results if result["errors"] == 0]
    return {
        "peak_requests_per_second": peak["requests_per_second"],
        "peak_concurrency": peak["concurrency"],
        "highest_error_free_concurrency_tested": max(
            (result["concurrency"] for result in error_free), default=0
        ),
    }


async def benchmark(full: bool) -> dict:
    run_id = time.time_ns()
    levels = FULL_LEVELS if full else QUICK_LEVELS
    workloads = ("hot", "sharded") if full else ("hot",)
    repetitions = 2 if full else 1
    account_count = SHARDED_ACCOUNT_PAIRS * 2 if full else 2
    limits = httpx.Limits(
        max_connections=max(levels),
        max_keepalive_connections=max(levels),
    )
    timeout = httpx.Timeout(60.0)

    async with httpx.AsyncClient(base_url=API_URL, limits=limits, timeout=timeout) as client:
        accounts = [
            await create_account(client, f"http-bench-{run_id}-{index}")
            for index in range(account_count)
        ]
        await run_trial(client, accounts, "hot", 5, 50, f"warmup-{run_id}")

        workload_results = {}
        for workload in workloads:
            results = []
            for level in levels:
                requests = min(500, max(100, level * 10)) if full else 200
                print(f"Running workload={workload} concurrency={level} requests={requests}...")
                results.append(
                    await run_level(
                        client,
                        accounts,
                        workload,
                        level,
                        requests,
                        repetitions,
                        run_id,
                    )
                )
            workload_results[workload] = {
                "summary": summarize(results),
                "results": results,
            }
        reconciliation = (await client.get("/admin/reconciliation")).json()

    output = {
        "endpoint": "POST /transfers",
        "mode": "full" if full else "quick",
        "environment": "Docker Desktop, one Uvicorn worker, PostgreSQL pool size 20",
        "workloads": {
            "hot": "opposing transfers between the same two accounts",
            "sharded": "transfers spread over ten independent account pairs",
        },
        "benchmarks": workload_results,
        "reconciliation_balanced": reconciliation["balanced"],
    }
    assert reconciliation["balanced"], reconciliation
    Path("http-benchmark-results.json").write_text(json.dumps(output, indent=2))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="run the full saturation matrix")
    args = parser.parse_args()
    output = asyncio.run(benchmark(args.full))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

