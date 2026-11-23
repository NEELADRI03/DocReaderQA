import uuid
from collections.abc import AsyncIterator

import httpx2
import pytest
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.session import get_session
from app.main import app
from app.security import verify_password

pytestmark = pytest.mark.anyio

REGISTER = "/api/v1/auth/register"
PASSWORD = "correct horse battery staple"


@pytest.fixture
async def client() -> AsyncIterator[httpx2.AsyncClient]:
    # Calls the app in-process; nothing listens on a port
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sessions(
    database_url: str, alembic_config: Config
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
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


def new_email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


# --- Validation: rejected before the database is touched ------------------------


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": "ann@example.com", "password": "short"}, "password"),
        ({"email": "ann@example.com", "password": "x" * 129}, "password"),
        ({"password": PASSWORD}, "email"),
    ],
)
async def test_invalid_input_uses_the_error_envelope(
    client: httpx2.AsyncClient, body: dict[str, str], field: str
) -> None:
    response = await client.post(REGISTER, json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == [field]


async def test_validation_error_does_not_echo_the_password(client: httpx2.AsyncClient) -> None:
    response = await client.post(REGISTER, json={"email": "nope", "password": "hunter2"})

    assert response.status_code == 422
    assert "hunter2" not in response.text


async def test_malformed_json_uses_the_error_envelope(client: httpx2.AsyncClient) -> None:
    response = await client.post(
        REGISTER, content=b'{"email": ', headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == ["body"]


async def test_unknown_route_uses_the_error_envelope(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


# --- Registration against a real database (TEST_DATABASE_URL) -------------------


async def test_register_creates_a_user_with_a_hashed_password(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    email = new_email()

    response = await client.post(REGISTER, json={"email": email, "password": PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert set(body) == {"id", "email", "created_at"}

    async with sessions() as session:
        user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert str(user.id) == body["id"]
    assert user.password_hash is not None
    assert user.password_hash != PASSWORD
    assert verify_password(user.password_hash, PASSWORD)


async def test_email_is_stored_lower_case(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    email = new_email()

    response = await client.post(REGISTER, json={"email": email.upper(), "password": PASSWORD})

    assert response.status_code == 201
    assert response.json()["email"] == email


async def test_same_email_twice_is_a_conflict(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    email = new_email()
    first = await client.post(REGISTER, json={"email": email, "password": PASSWORD})

    # Differs only in case, so it is the same account
    second = await client.post(REGISTER, json={"email": email.upper(), "password": "another-pass"})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {
        "error": {"code": "EMAIL_TAKEN", "message": "An account with this email already exists."}
    }
