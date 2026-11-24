import uuid
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models import Collection, User

# Async tests run on asyncio through the anyio plugin that comes with FastAPI
pytestmark = pytest.mark.anyio


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
