import uuid
from collections.abc import AsyncIterator

import httpx2
import pytest
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.session import get_session
from app.main import app
from app.security import verify_password
from app.tokens import create_token, decode_token

pytestmark = pytest.mark.anyio

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
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


# --- Login and refresh (S0.3.2) -------------------------------------------------

INVALID_CREDENTIALS = {
    "error": {"code": "INVALID_CREDENTIALS", "message": "The email or password is incorrect."}
}
INVALID_TOKEN = {
    "error": {"code": "INVALID_TOKEN", "message": "The refresh token is invalid or has expired."}
}


async def register_user(client: httpx2.AsyncClient) -> tuple[str, uuid.UUID]:
    email = new_email()
    response = await client.post(REGISTER, json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return email, uuid.UUID(response.json()["id"])


async def login_user(client: httpx2.AsyncClient) -> tuple[uuid.UUID, dict[str, str]]:
    email, user_id = await register_user(client)
    response = await client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return user_id, response.json()


# Validation: no database needed


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "ann@example.com"}, "password"),
        ({"password": PASSWORD}, "email"),
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": "ann@example.com", "password": "x" * 129}, "password"),
    ],
)
async def test_invalid_login_input_is_a_validation_error(
    client: httpx2.AsyncClient, body: dict[str, str], field: str
) -> None:
    response = await client.post(LOGIN, json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == [field]


async def test_login_validation_error_does_not_echo_the_password(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.post(LOGIN, json={"email": "nope", "password": "hunter2"})

    assert response.status_code == 422
    assert "hunter2" not in response.text


async def test_refresh_without_a_token_is_a_validation_error(client: httpx2.AsyncClient) -> None:
    response = await client.post(REFRESH, json={})

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["refresh_token"]


# Login against a real database


async def test_login_returns_tokens_for_the_user(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    email, user_id = await register_user(client)

    response = await client.post(LOGIN, json={"email": email, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert decode_token(body["access_token"], "access") == user_id
    assert decode_token(body["refresh_token"], "refresh") == user_id


async def test_login_email_is_case_insensitive(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    email, _ = await register_user(client)

    response = await client.post(LOGIN, json={"email": email.upper(), "password": PASSWORD})

    assert response.status_code == 200


async def test_wrong_password_and_unknown_email_look_the_same(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    email, _ = await register_user(client)

    wrong_password = await client.post(LOGIN, json={"email": email, "password": "wrong-pass"})
    unknown_email = await client.post(LOGIN, json={"email": new_email(), "password": PASSWORD})

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json() == INVALID_CREDENTIALS
        assert response.headers["www-authenticate"] == "Bearer"


async def test_user_without_a_password_hash_cannot_log_in(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # The column is nullable for future SSO users; they must not get in with any password
    email = new_email()
    async with sessions() as session:
        session.add(User(email=email, password_hash=None))
        await session.commit()

    response = await client.post(LOGIN, json={"email": email, "password": PASSWORD})

    assert response.status_code == 401
    assert response.json() == INVALID_CREDENTIALS


# Refresh against a real database


async def test_refresh_returns_new_tokens(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user_id, tokens = await login_user(client)

    response = await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_token(body["access_token"], "access") == user_id
    assert decode_token(body["refresh_token"], "refresh") == user_id
    assert body["refresh_token"] != tokens["refresh_token"]


async def test_access_token_cannot_be_used_to_refresh(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, tokens = await login_user(client)

    response = await client.post(REFRESH, json={"refresh_token": tokens["access_token"]})

    assert response.status_code == 401
    assert response.json() == INVALID_TOKEN
    assert response.headers["www-authenticate"] == "Bearer"


async def test_garbage_refresh_token_is_rejected(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.post(REFRESH, json={"refresh_token": "not-a-jwt"})

    assert response.status_code == 401
    assert response.json() == INVALID_TOKEN


async def test_refresh_for_a_deleted_user_is_rejected(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, user_id = await register_user(client)
    token = create_token(user_id, "refresh")
    async with sessions() as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()

    response = await client.post(REFRESH, json={"refresh_token": token})

    assert response.status_code == 401
    assert response.json() == INVALID_TOKEN
