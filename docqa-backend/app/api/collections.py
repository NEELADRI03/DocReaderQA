import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.errors import ApiError, ErrorResponse
from app.db.models import Collection
from app.schemas.collections import CollectionRead

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get(
    "/{collection_id}", responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}
)
async def get_collection(
    collection_id: uuid.UUID, user: CurrentUser, session: Session
) -> CollectionRead:

    # The owner check is part of the query so another
    # user's collection is never loaded
    collection = await session.scalar(
        select(Collection).where(Collection.id == collection_id, Collection.user_id == user.id)
    )

    if collection is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "COLLECTION_NOT_FOUND", "The collection does not exist."
        )

    return CollectionRead.model_validate(collection)
