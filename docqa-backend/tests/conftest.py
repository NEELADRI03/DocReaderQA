import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

# Settings has required fields. Give them test values before any app module reads them.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")


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
