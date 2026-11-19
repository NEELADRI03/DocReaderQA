from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.db.session import engine

# api_router = APIRouter(prefix="/api/v1")


# @api_router.get("/health")
# async def health() -> dict[str, str]:
#     return {"status": "ok"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(title="DocQA API", lifespan=lifespan)
app.include_router(api_router)
