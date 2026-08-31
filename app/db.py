from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.config import settings

pool = AsyncConnectionPool(
    conninfo=settings.database_url,
    min_size=settings.db_pool_min_size,
    max_size=settings.db_pool_max_size,
    open=False,
)


@asynccontextmanager
async def connection() -> AsyncIterator[AsyncConnection]:
    async with pool.connection() as conn:
        yield conn

