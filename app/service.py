import hashlib
import json

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.errors import Conflict, InsufficientFunds, NotFound
from app.models import AccountCreate, TransferCreate


def request_fingerprint(request: TransferCreate) -> str:
    canonical = json.dumps(
        {
            "amount": format(request.amount, ".2f"),
            "currency": request.currency,
            "from": str(request.from_account_id),
            "to": str(request.to_account_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def create_account(conn: AsyncConnection, request: AccountCreate) -> dict:
    async with conn.transaction():
        account = await conn.execute(
            """INSERT INTO accounts(name, currency, balance)
               VALUES (%s, %s, %s) RETURNING id, name, currency, balance""",
            (request.name, request.currency, request.opening_balance),
        )
        row = await account.fetchone()
        if request.opening_balance:
            entry = await conn.execute(
                """INSERT INTO journal_entries(kind, reference)
                   VALUES ('opening', %s) RETURNING id""",
                (f"opening:{row[0]}",),
            )
            entry_id = (await entry.fetchone())[0]
            equity = await conn.execute(
                "SELECT id FROM accounts WHERE is_system AND currency = %s",
                (request.currency,),
            )
            equity_id = (await equity.fetchone())[0]
            await conn.execute(
                """INSERT INTO postings(journal_entry_id, account_id, amount)
                   VALUES (%s, %s, %s), (%s, %s, %s)""",
                (
                    entry_id,
                    row[0],
                    request.opening_balance,
                    entry_id,
                    equity_id,
                    -request.opening_balance,
                ),
            )
            await conn.execute(
                "UPDATE accounts SET balance = balance - %s WHERE id = %s",
                (request.opening_balance, equity_id),
            )
        return dict(zip(("id", "name", "currency", "balance"), row, strict=True))


async def transfer(conn: AsyncConnection, request: TransferCreate) -> dict:
    fingerprint = request_fingerprint(request)
    async with conn.transaction():
        inserted = await conn.execute(
            """INSERT INTO idempotency_keys(key, request_hash)
               VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING key""",
            (request.idempotency_key, fingerprint),
        )
        owns_key = await inserted.fetchone()
        if not owns_key:
            existing_cursor = await conn.execute(
                """SELECT request_hash, response FROM idempotency_keys
                   WHERE key = %s FOR UPDATE""",
                (request.idempotency_key,),
            )
            existing = await existing_cursor.fetchone()
            if existing[0] != fingerprint:
                raise Conflict("idempotency key was already used for a different request")
            if existing[1] is None:
                raise Conflict("matching request is still in progress; retry shortly")
            response = existing[1]
            response["replayed"] = True
            return response

        # All callers lock accounts in UUID order, eliminating transfer A->B/B->A deadlocks.
        account_ids = sorted((request.from_account_id, request.to_account_id), key=str)
        rows_cursor = await conn.execute(
            """SELECT id, currency, balance FROM accounts
               WHERE id = ANY(%s) ORDER BY id FOR UPDATE""",
            (account_ids,),
        )
        rows = await rows_cursor.fetchall()
        if len(rows) != 2:
            raise NotFound("one or both accounts do not exist")
        accounts = {row[0]: row for row in rows}
        source = accounts[request.from_account_id]
        destination = accounts[request.to_account_id]
        if source[1] != request.currency or destination[1] != request.currency:
            raise Conflict("both account currencies must match the transfer currency")
        if source[2] < request.amount:
            raise InsufficientFunds("insufficient funds")

        journal_cursor = await conn.execute(
            """INSERT INTO journal_entries(kind, reference)
               VALUES ('transfer', %s) RETURNING id""",
            (request.idempotency_key,),
        )
        journal_id = (await journal_cursor.fetchone())[0]
        transfer_cursor = await conn.execute(
            """INSERT INTO transfers(journal_entry_id, from_account_id, to_account_id,
                                      amount, currency, idempotency_key)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                journal_id,
                request.from_account_id,
                request.to_account_id,
                request.amount,
                request.currency,
                request.idempotency_key,
            ),
        )
        transfer_id = (await transfer_cursor.fetchone())[0]
        await conn.execute(
            """INSERT INTO postings(journal_entry_id, account_id, amount)
               VALUES (%s, %s, %s), (%s, %s, %s)""",
            (
                journal_id,
                request.from_account_id,
                -request.amount,
                journal_id,
                request.to_account_id,
                request.amount,
            ),
        )
        await conn.execute(
            """UPDATE accounts SET balance = CASE
                 WHEN id = %s THEN balance - %s ELSE balance + %s END
               WHERE id = ANY(%s)""",
            (request.from_account_id, request.amount, request.amount, account_ids),
        )
        response = {
            "id": str(transfer_id),
            "from_account_id": str(request.from_account_id),
            "to_account_id": str(request.to_account_id),
            "amount": format(request.amount, ".2f"),
            "currency": request.currency,
            "status": "posted",
            "replayed": False,
        }
        await conn.execute(
            "UPDATE idempotency_keys SET response = %s WHERE key = %s",
            (json.dumps(response), request.idempotency_key),
        )
        return response


async def reconcile(conn: AsyncConnection) -> dict:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        """SELECT a.id, a.balance, COALESCE(SUM(p.amount), 0) AS ledger_balance
           FROM accounts a LEFT JOIN postings p ON p.account_id = a.id
           GROUP BY a.id HAVING a.balance <> COALESCE(SUM(p.amount), 0)
           ORDER BY a.id"""
    )
    mismatches = [dict(row) for row in await cursor.fetchall()]
    count_cursor = await conn.execute("SELECT count(*) FROM accounts")
    count = (await count_cursor.fetchone())[0]
    return {"accounts_checked": count, "mismatches": mismatches, "balanced": not mismatches}

