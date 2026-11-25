import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import jwt
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Collection, User
from app.main import app
from app.tokens import ALGORITHM, create_token

pytestmark = pytest.mark.anyio

ME = "/api/v1/auth/me"

# Every other route under /api/v1 must answer 401 without a token
PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
}

NOT_AUTHENTICATED = {
    "error": {
        "code": "NOT_AUTHENTICATED",
        "message": "Send an access token in the Authorization header.",
    }
}
INVALID_TOKEN = {
    "error": {"code": "INVALID_TOKEN", "message": "The access token is invalid or has expired."}
}
COLLECTION_NOT_FOUND = {
    "error": {"code": "COLLECTION_NOT_FOUND", "message": "The collection does not exist."}
}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def expired_access_token() -> str:
    past = datetime.now(UTC) - timedelta(minutes=1)
    claims = {"sub": str(uuid.uuid4()), "type": "access", "exp": past}
    return jwt.encode(claims, get_settings().jwt_secret.get_secret_value(), algorithm=ALGORITHM)


async def add_user(sessions: async_sessionmaker[AsyncSession]) -> User:
    # Straight into the table: these tests are about tokens, not passwords
    async with sessions() as session:
        user = User(email=f"{uuid.uuid4().hex[:12]}@example.com")
        session.add(user)
        await session.commit()
    return user


async def add_collection(sessions: async_sessionmaker[AsyncSession], owner: User) -> Collection:
    async with sessions() as session:
        collection = Collection(user_id=owner.id, name="Contracts")
        session.add(collection)
        await session.commit()
    return collection


# --- Rejected before the database is touched ------------------------------------


async def test_missing_token_is_401(client: httpx2.AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.json() == NOT_AUTHENTICATED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_other_auth_scheme_is_401(client: httpx2.AsyncClient) -> None:
    response = await client.get(ME, headers={"Authorization": "Basic YW5uOnB3"})

    assert response.status_code == 401
    assert response.json() == NOT_AUTHENTICATED


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        expired_access_token(),
        # A refresh token lives for days; it must not open API routes
        create_token(uuid.uuid4(), "refresh"),
    ],
    ids=["garbage", "expired", "refresh-token"],
)
async def test_invalid_token_is_401(client: httpx2.AsyncClient, token: str) -> None:
    response = await client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json() == INVALID_TOKEN
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'


def _protected_routes() -> list[tuple[str, str]]:
    # Read from the OpenAPI schema: every route the API documents, with its full path
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    routes = [(method.upper(), path) for path, ops in paths.items() for method in ops]
    protected = [route for route in routes if route not in PUBLIC_ROUTES]
    assert protected, "found no protected routes; is the route listing broken?"
    return protected


@pytest.mark.parametrize(("method", "path"), _protected_routes())
async def test_every_other_route_needs_a_token(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    # Fill path parameters such as {collection_id} with a well-formed ID
    url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)

    response = await client.request(method, url)

    assert response.status_code == 401, f"{method} {path} answered without a token"


# --- Against a real database (TEST_DATABASE_URL) --------------------------------


async def test_me_returns_the_token_owner(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await add_user(sessions)

    response = await client.get(ME, headers=bearer(create_token(user.id, "access")))

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
    assert response.json()["email"] == user.email


async def test_token_of_a_deleted_user_is_401(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await add_user(sessions)
    token = create_token(user.id, "access")
    async with sessions() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

    response = await client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json() == INVALID_TOKEN


async def test_owner_can_read_their_collection(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    ann = await add_user(sessions)
    collection = await add_collection(sessions, ann)

    response = await client.get(
        f"/api/v1/collections/{collection.id}", headers=bearer(create_token(ann.id, "access"))
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(collection.id)
    assert response.json()["name"] == "Contracts"
    assert set(response.json()) == {"id", "name", "created_at"}


async def test_user_cannot_read_another_users_collection(
    client: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    ann = await add_user(sessions)
    bob = await add_user(sessions)
    anns_collection = await add_collection(sessions, ann)
    bobs_token = bearer(create_token(bob.id, "access"))

    someone_elses = await client.get(
        f"/api/v1/collections/{anns_collection.id}", headers=bobs_token
    )
    nonexistent = await client.get(f"/api/v1/collections/{uuid.uuid4()}", headers=bobs_token)

    # Bob gets exactly what he'd get for an ID that doesn't exist, so he learns nothing
    for response in (someone_elses, nonexistent):
        assert response.status_code == 404
        assert response.json() == COLLECTION_NOT_FOUND
