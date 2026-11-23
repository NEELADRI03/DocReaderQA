from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.errors import ApiError, ErrorResponse
from app.db.models import User
from app.db.session import get_session
from app.schemas.auth import RegisterRequest, UserRead
from app.security import hash_password

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]


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
