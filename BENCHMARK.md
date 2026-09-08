# HTTP Capacity Report

Measured on 2026-08-22 against the real `POST /transfers` endpoint.

## Setup

- Docker Desktop laptop environment
- One Uvicorn worker
- PostgreSQL connection pool: 20
- Concurrency levels: 1, 5, 10, 20, 40, 80, 120, 160
- Two repetitions per level
- 9,600 measured requests across both workloads
- Latency measures actual HTTP request time after entering the client concurrency gate
- Every response was HTTP 201; final ledger reconciliation was balanced

The request count grows with concurrency: 200 total at levels 1–10, 400 at 20, 800 at 40, and
1,000 at levels 80–160.

## Same two accounts (high row-lock contention)

| Concurrency | Requests | Requests/s | p50 ms | p95 ms | p99 ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 200 | 19.1 | 52.05 | 55.36 | 56.78 | 56.94 | 0 |
| 5 | 200 | 91.3 | 52.38 | 59.87 | 66.11 | 72.07 | 0 |
| 10 | 200 | **163.9** | 55.76 | 80.05 | 94.58 | 99.43 | 0 |
| 20 | 400 | 106.8 | 148.81 | 371.05 | 517.32 | 660.11 | 0 |
| 40 | 800 | 85.4 | 357.79 | 1089.93 | 1683.77 | 3059.37 | 0 |
| 80 | 1,000 | 82.7 | 634.14 | 2432.85 | 3900.14 | 5262.67 | 0 |
| 120 | 1,000 | 76.4 | 1101.98 | 3768.62 | 5195.34 | 5872.24 | 0 |
| 160 | 1,000 | 79.4 | 1377.89 | 4923.46 | 5861.19 | 6170.88 | 0 |

## Ten independent account pairs

| Concurrency | Requests | Requests/s | p50 ms | p95 ms | p99 ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 200 | 18.7 | 52.41 | 57.90 | 59.32 | 60.43 | 0 |
| 5 | 200 | 86.4 | 56.22 | 64.30 | 70.07 | 82.32 | 0 |
| 10 | 200 | **128.0** | 69.18 | 106.79 | 138.54 | 147.89 | 0 |
| 20 | 400 | 84.0 | 175.20 | 570.58 | 829.73 | 989.78 | 0 |
| 40 | 800 | 60.0 | 484.11 | 1772.69 | 2628.69 | 3186.97 | 0 |
| 80 | 1,000 | 51.9 | 996.45 | 4097.79 | 5818.60 | 9275.74 | 0 |
| 120 | 1,000 | 62.3 | 1264.52 | 4887.25 | 6808.41 | 8856.88 | 0 |
| 160 | 1,000 | 87.2 | 1200.86 | 4429.88 | 5847.28 | 6276.43 | 0 |

## Interpretation

- Peak measured throughput occurs at concurrency 10: 163.9 requests/s for the hot-account case.
- The system remained correct and error-free through concurrency 160, but that is not a useful
  operating point: tail latency grew into seconds while throughput did not improve.
- A practical operating point for this configuration is around concurrency 10. Capacity should
  be stated with a latency target, not only as the highest number of connected clients.
- Sharding account pairs did not improve this single-worker laptop result. Therefore row locks are
  not the only bottleneck here; HTTP/database transaction overhead and pool contention also matter.

Run the same matrix with:

```bash
python -m tests.http_benchmark --full
```
