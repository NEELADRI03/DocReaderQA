import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models import Collection, User

# Async tests run on asyncio through the anyio plugin that comes with FastAPI
pytestmark = pytest.mark.anyio


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
async def session(database_url: str, alembic_config: Config) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


def test_models_match_migrations(alembic_config: Config) -> None:
    # Fails when a model changed but nobody ran `alembic revision --autogenerate`
    command.check(alembic_config)


def test_migrations_downgrade_and_upgrade_again(alembic_config: Config) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


async def test_vector_extension_is_enabled(session: AsyncSession) -> None:
    query = text("SELECT extname FROM pg_extension WHERE extname = 'vector'")

    assert await session.scalar(query) == "vector"


async def test_deleting_a_user_deletes_their_collections(session: AsyncSession) -> None:
    user = User(email=f"{uuid.uuid4()}@example.com")
    session.add(user)
    await session.flush()
    collection = Collection(user_id=user.id, name="Contracts")
    session.add(collection)
    await session.commit()

    await session.delete(user)
    await session.commit()

    remaining = await session.scalar(select(Collection).where(Collection.id == collection.id))
    assert remaining is None


async def test_email_is_unique(session: AsyncSession) -> None:
    email = f"{uuid.uuid4()}@example.com"
    session.add(User(email=email))
    await session.commit()

    session.add(User(email=email))
    with pytest.raises(IntegrityError):
        await session.commit()
