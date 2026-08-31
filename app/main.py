from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import connection, pool


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.open()
    yield
    await pool.close()


app = FastAPI(title="Transactional Ledger", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    async with connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}

