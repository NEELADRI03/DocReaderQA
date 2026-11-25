from fastapi import APIRouter, Depends

from app.api import auth, collections, health
from app.api.deps import get_current_user

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)

protected = APIRouter(dependencies=[Depends(get_current_user)])
protected.include_router(collections.router)
api_router.include_router(protected)
