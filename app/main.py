from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db import connection, pool
from app.errors import LedgerError, NotFound
from app.models import Account, AccountCreate, ReconciliationReport, Transfer, TransferCreate
from app.service import create_account, reconcile, transfer


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.open()
    yield
    await pool.close()


app = FastAPI(title="Transactional Ledger", version="0.1.0", lifespan=lifespan)


@app.exception_handler(LedgerError)
async def ledger_error(_: Request, exc: LedgerError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict:
    async with connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/accounts", response_model=Account, status_code=201)
async def post_account(body: AccountCreate) -> dict:
    async with connection() as conn:
        return await create_account(conn, body)


@app.get("/accounts/{account_id}", response_model=Account)
async def get_account(account_id: UUID) -> dict:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id, name, currency, balance FROM accounts WHERE id = %s AND NOT is_system",
            (account_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise NotFound("account does not exist")
        return dict(zip(("id", "name", "currency", "balance"), row, strict=True))


@app.post("/transfers", response_model=Transfer, status_code=201)
async def post_transfer(body: TransferCreate) -> dict:
    async with connection() as conn:
        return await transfer(conn, body)


@app.get("/admin/reconciliation", response_model=ReconciliationReport)
async def reconciliation() -> dict:
    async with connection() as conn:
        return await reconcile(conn)
