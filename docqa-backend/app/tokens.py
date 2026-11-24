import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.config import get_settings

ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    """The token is malformed, tampered with, expired or of the wrong type"""


def token_lifetime(token_type: TokenType) -> timedelta:

    settings = get_settings()

    if token_type == "access":
        return timedelta(minutes=settings.access_token_minutes)
    return timedelta(days=settings.refresh_token_days)


def create_token(user_id: uuid.UUID, token_type: TokenType) -> str:

    now = datetime.now(UTC)

    claims = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + token_lifetime(token_type),
        "jti": uuid.uuid4().hex,
    }

    secret = get_settings().jwt_secret.get_secret_value()
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(token: str, token_type: TokenType) -> uuid.UUID:
    """Return the User Id of the valid token of the given type, or raise InvalidTokenError"""

    secret = get_settings().jwt_secret.get_secret_value()

    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "type"]}
        )

        # Without this a refresh token, which lives for days, would work as an access token
        if claims["type"] != token_type:
            raise InvalidTokenError(f"expected a {token_type} token")
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
