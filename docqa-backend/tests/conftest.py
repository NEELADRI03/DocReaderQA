import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Settings has required fields. Give them test values before any app module reads them.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "change-me-to-a-random-string-of-32-characters-or-more-chars")


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    # These tests drop every table, so refuse anything that isn't a throwaway database
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point at a database whose name ends in _test")
    return url


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    # Start from an empty database, run every migration, and clean up afterwards
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield config
    command.downgrade(config, "base")


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    # Imported here, not at the top: the app reads its settings on import, after the env above
    from app.main import app

    # Calls the app in-process; nothing listens on a port
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sessions(
    database_url: str, alembic_config: Config
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    from app.db.session import get_session
    from app.main import app

    # The app's routes get sessions on the test database instead of DATABASE_URL
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()
