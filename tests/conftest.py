import os

import pytest
import pytest_asyncio
from psycopg import AsyncConnection


@pytest_asyncio.fixture
async def conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for integration tests")
    connection = await AsyncConnection.connect(url)
    try:
        yield connection
    finally:
        await connection.close()

