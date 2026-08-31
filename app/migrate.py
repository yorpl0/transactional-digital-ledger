import asyncio
from pathlib import Path

from psycopg import AsyncConnection

from app.config import settings


async def main() -> None:
    sql = Path("migrations/001_initial.sql").read_text()
    async with await AsyncConnection.connect(settings.database_url) as conn:
        exists = await conn.execute("SELECT to_regclass('public.accounts')")
        if (await exists.fetchone())[0] is None:
            await conn.execute(sql)
            await conn.commit()
            print("applied migrations/001_initial.sql")
        else:
            print("schema already initialized")


if __name__ == "__main__":
    asyncio.run(main())

