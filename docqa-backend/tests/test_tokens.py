import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.tokens import ALGORITHM, InvalidTokenError, create_token, decode_token


def _sign(claims: dict[str, object], secret: str | None = None) -> str:
    key = secret or get_settings().jwt_secret.get_secret_value()
    return jwt.encode(claims, key, algorithm=ALGORITHM)


def _in_a_day() -> datetime:
    return datetime.now(UTC) + timedelta(days=1)


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()

    assert decode_token(create_token(user_id, "access"), "access") == user_id


def test_refresh_token_round_trip() -> None:
    user_id = uuid.uuid4()

    assert decode_token(create_token(user_id, "refresh"), "refresh") == user_id


def test_refresh_token_is_not_an_access_token() -> None:
    token = create_token(uuid.uuid4(), "refresh")

    with pytest.raises(InvalidTokenError):
        decode_token(token, "access")


def test_access_token_is_not_a_refresh_token() -> None:
    token = create_token(uuid.uuid4(), "access")

    with pytest.raises(InvalidTokenError):
        decode_token(token, "refresh")


def test_tokens_are_unique() -> None:
    # Same user, same second: the jti claim still makes them differ
    user_id = uuid.uuid4()

    assert create_token(user_id, "refresh") != create_token(user_id, "refresh")


def test_access_token_lifetime_matches_settings() -> None:
    token = create_token(uuid.uuid4(), "access")
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["exp"] - claims["iat"] == get_settings().access_token_minutes * 60


def test_refresh_token_lifetime_matches_settings() -> None:
    token = create_token(uuid.uuid4(), "refresh")
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["exp"] - claims["iat"] == get_settings().refresh_token_days * 24 * 60 * 60


def test_token_holds_only_the_expected_claims() -> None:
    # The payload is readable by anyone, so nothing private may be in it
    token = create_token(uuid.uuid4(), "access")
    claims = jwt.decode(token, options={"verify_signature": False})

    assert set(claims) == {"sub", "type", "iat", "exp", "jti"}


def test_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(minutes=1)
    token = _sign({"sub": str(uuid.uuid4()), "type": "access", "exp": past})

    with pytest.raises(InvalidTokenError):
        decode_token(token, "access")


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        "",
        # Signed with another key
        _sign(
            {"sub": str(uuid.uuid4()), "type": "access", "exp": _in_a_day()},
            secret="some-other-secret-that-is-32-chars-or-more",
        ),
        # No expiry
        _sign({"sub": str(uuid.uuid4()), "type": "access"}),
        # No subject
        _sign({"type": "access", "exp": _in_a_day()}),
        # No type
        _sign({"sub": str(uuid.uuid4()), "exp": _in_a_day()}),
        # Subject is not a user ID
        _sign({"sub": "admin", "type": "access", "exp": _in_a_day()}),
    ],
    ids=["garbage", "empty", "wrong-key", "no-exp", "no-sub", "no-type", "bad-sub"],
)
def test_invalid_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_token(token, "access")


def test_tampered_payload_is_rejected() -> None:
    # Swap in another token's payload but keep the original signature
    header, _, signature = create_token(uuid.uuid4(), "access").split(".")
    _, other_payload, _ = create_token(uuid.uuid4(), "access").split(".")

    with pytest.raises(InvalidTokenError):
        decode_token(f"{header}.{other_payload}.{signature}", "access")


def test_unsigned_token_is_rejected() -> None:
    # alg "none" has no signature at all; anyone could write one
    claims = {"sub": str(uuid.uuid4()), "type": "access", "exp": _in_a_day()}
    token = jwt.encode(claims, None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        decode_token(token, "access")
