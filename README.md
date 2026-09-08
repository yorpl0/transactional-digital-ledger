# Transactional Digital Ledger

> **Status:** complete. The repository includes the ledger API, PostgreSQL invariants, focused
> integration tests, concurrency demo, invariant stress test, and repeatable HTTP saturation
> benchmark.

A compact FastAPI and PostgreSQL backend focused on one difficult problem: moving money correctly
under failures, retries, and concurrent requests.

The service records transfers as immutable double-entry journal entries, executes the full transfer
path inside one ACID transaction, prevents lost updates with row-level locks, and uses persistent
idempotency keys so retrying a request cannot move money twice.

## What it demonstrates

- **Double-entry accounting:** every debit has an equal credit, and deferred PostgreSQL triggers
  reject unbalanced journal entries at commit.
- **Atomic transfers:** idempotency, validation, account locking, postings, balance updates, and the
  stored response commit or roll back together.
- **Concurrency control:** `SELECT ... FOR UPDATE` protects balances from simultaneous updates.
- **Deadlock avoidance:** account UUIDs are sorted before locking, so opposing A → B and B → A
  transfers acquire locks in the same order.
- **Retry safety:** a unique idempotency key is tied to a SHA-256 request fingerprint; identical
  retries replay the original response, while incompatible reuse is rejected.
- **Immutable history:** database triggers reject updates and deletes to journal entries and
  postings.
- **Reconciliation:** cached account balances are checked against balances derived from immutable
  postings.

## Transfer flow

When Alice sends money to Bob, the service performs the following inside one PostgreSQL transaction:

1. Claims or validates the idempotency key.
2. Locks both accounts in deterministic UUID order.
3. Validates account existence, currency, and available funds.
4. Creates a journal entry and transfer record.
5. Writes an equal debit and credit.
6. Updates both cached balances.
7. Stores the completed response for safe replay.

If any step fails, the entire operation is rolled back. Alice cannot be charged without Bob being
credited.

## Architecture

```text
Client
  │
  ▼
FastAPI REST API
  │
  ├── Validation and idempotency
  ├── Deterministic account locking
  ├── Double-entry journal postings
  └── Balance reconciliation
  │
  ▼
PostgreSQL
```

The project intentionally uses one application and one database. Redis, Celery, Kafka,
microservices, and Kubernetes are excluded because they do not improve the core correctness
demonstration.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/accounts` | Create an account and balanced opening entry |
| `GET` | `/accounts/{id}` | Retrieve an account and current balance |
| `POST` | `/transfers` | Execute an atomic, retry-safe transfer |
| `GET` | `/admin/reconciliation` | Compare cached and ledger-derived balances |
| `GET` | `/health` | Verify database connectivity |

FastAPI exposes interactive OpenAPI documentation at `/docs`.

## Correctness verification

The concurrency test creates funded accounts, launches simultaneous opposing transfers, and
deliberately duplicates requests. It then checks both the aggregate balance and full ledger
reconciliation.

```text
Logical transfers      20 opposing transfers
Requests submitted     24 (4 retries)
Idempotent replays     4
Total before / after   2000.00 / 2000.00
Money created or lost  0.00
Ledger reconciliation PASS
```

The PostgreSQL-backed test suite also covers deterministic request fingerprints, input validation,
duplicate transfer replay, and opposite-direction transfers without deadlock.

## Measured HTTP capacity

A host-to-container saturation test exercised the real `POST /transfers` endpoint across
concurrency levels from 1 to 160. The test used one Uvicorn worker, a PostgreSQL connection pool of
20, two repetitions per level, and two workloads:

- repeated transfers between the same two accounts;
- transfers distributed across ten independent account pairs.

Across **9,600 measured requests**, every request succeeded and final ledger reconciliation
remained balanced.

| Workload | Peak throughput | Peak concurrency | Highest error-free concurrency tested |
|---|---:|---:|---:|
| Same two accounts | **163.9 requests/s** | 10 | 160 |
| Ten independent pairs | **128.0 requests/s** | 10 | 160 |

For the same-account workload at concurrency 10:

- p50 latency: **55.76 ms**
- p95 latency: **80.05 ms**
- p99 latency: **94.58 ms**

Concurrency 10 was the practical saturation point on the tested laptop. The system remained
error-free at concurrency 160, but p95 latency rose to approximately 4.9 seconds, so 160 is a test
ceiling rather than a recommended operating point. These are local Docker Desktop measurements,
not production capacity claims.

## Technology

- Python
- FastAPI
- PostgreSQL
- Psycopg
- Docker Compose
- Pytest
- HTTPX

## Design decisions

### Why keep a cached balance?

Immutable postings remain the accounting source of truth, but summing the full history for every
request is inefficient. A cached balance supports quick reads and a simple locked overdraft check;
reconciliation detects any drift from the journal.

### Why pessimistic row locking?

Transfers may contend on the same balance. Locking makes the correctness rule explicit and avoids
retry loops inside the transfer path. Optimistic concurrency could reduce lock duration under low
contention, but would require version checks and retries when accounts are hot.

### Why store idempotency in PostgreSQL?

The idempotency claim must commit or roll back with the financial transaction. Keeping both within
PostgreSQL provides one atomic boundary; a separate cache could disagree with the ledger after a
partial failure.

## Scope

This is an accounting and concurrency project, not a complete banking platform. Authentication,
payment-provider integration, foreign exchange, fees, fraud detection, regulatory compliance,
frontend applications, and cloud deployment are intentionally out of scope.
