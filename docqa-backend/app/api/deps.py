from typing import Annotated

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import User
from app.db.session import get_session
from app.tokens import InvalidTokenError, decode_token

Session = Annotated[AsyncSession, Depends(get_session)]

BEARER = {"WWW-Authenticate": "Bearer"}
INVALID_BEARER = {"WWW-Authenticate": 'Bearer error="invalid_token"'}

# auto_error=False: a missing or non-Bearer header comes back as None, so we answer with our.
# own envelope and a 401. Also puts the Authorize button in /docs.
bearer_scheme = HTTPBearer(auto_error=False)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_current_user(credentials: Credentials, session: Session) -> User:

    if credentials is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "NOT_AUTHENTICATED",
            "Send an access token in the Authorization header.",
            headers=BEARER,
        )

    invalid = ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_TOKEN",
        "The access token is invalid or has expired.",
        headers=INVALID_BEARER,
    )

    try:
        user_id = decode_token(credentials.credentials, "access")
    except InvalidTokenError as exc:
        raise invalid from exc

    # The account may have been deleted since the token was issued
    user = await session.get(User, user_id)

    if user is None:
        raise invalid
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
