from fastapi import APIRouter,FastAPI

app = FastAPI(title="DocQA API")

api_router = APIRouter(prefix="/api/v1")

@api_router.get("/health")
async def health() -> dict[str,str]:
    return {"status":"ok"}

app.include_router(api_router)