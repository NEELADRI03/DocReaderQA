import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.errors import ApiError, ErrorResponse
from app.db.models import User
from app.db.session import get_session
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserRead
from app.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.tokens import InvalidTokenError, create_token, decode_token, token_lifetime

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]

BEARER = {"WWW-Authenticate": "Bearer"}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def register(body: RegisterRequest, session: Session) -> UserRead:

    password_hash = await run_in_threadpool(hash_password, body.password)

    user = User(email=body.email, password_hash=password_hash)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()

        if "uq_users_email" in str(exc.orig):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "EMAIL_TAKEN",
                "An account with this email already exists.",
            ) from exc
        raise

    await session.refresh(user)
    return UserRead.model_validate(user)


def _issue_tokens(user_id: uuid.UUID) -> TokenResponse:

    return TokenResponse(
        access_token=create_token(user_id, "access"),
        refresh_token=create_token(user_id, "refresh"),
        expires_in=int(token_lifetime("access").total_seconds()),
    )


@router.post("/login", responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
async def login(body: LoginRequest, session: Session) -> TokenResponse:

    user = await session.scalar(select(User).where(User.email == body.email))

    password_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    password_ok = await run_in_threadpool(verify_password, password_hash, body.password)

    if user is None or user.password_hash is None or not password_ok:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_CREDENTIALS",
            "The email or password is incorrect.",
            headers=BEARER,
        )

    return _issue_tokens(user.id)


@router.post("/refresh", responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
async def refresh(body: RefreshRequest, session: Session) -> TokenResponse:

    invalid = ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_CREDENTIALS",
        "The refresh token is invalid or has expired.",
        headers=BEARER,
    )

    try:
        user_id = decode_token(body.refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise invalid from exc

    if await session.get(User, user_id) is None:
        raise invalid

    return _issue_tokens(user_id)
