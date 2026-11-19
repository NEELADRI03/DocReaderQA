import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

import httpx2
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 3.0


class CheckResult(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: int
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckResult]


async def check_database(settings: Settings) -> None:
    # Goes through the app's engine, and also checks that migrations have run
    async with engine.connect() as connection:
        vector = await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )

    if vector is None:
        raise RuntimeError("vector extension missing, run: alembic upgrade head")


async def check_redis(settings: Settings) -> None:
    client = Redis.from_url(settings.redis_url)

    try:
        await client.ping()
    finally:
        await client.aclose()


def _with_tag(model: str) -> str:
    # Ollama lists "nomic-embed-text" as "nomic-embed-text:latest"
    return model if ":" in model else f"{model}:latest"


async def check_ollama(settings: Settings) -> None:
    async with httpx2.AsyncClient(base_url=settings.ollama_base_url) as client:
        response = await client.get("/api/tags")
        response.raise_for_status()

    pulled = {model["name"] for model in response.json()["models"]}

    missing = [
        name
        for name in (settings.llm_model, settings.embedding_model)
        if _with_tag(name) not in pulled
    ]

    if missing:
        raise RuntimeError(f"model not pulled: {', '.join(missing)}")


async def _run(check: Callable[[Settings], Awaitable[None]], settings: Settings) -> CheckResult:
    start = time.perf_counter()

    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await check(settings)
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        return CheckResult(status="error", latency_ms=_elapsed_ms(start), error=error)

    return CheckResult(status="ok", latency_ms=_elapsed_ms(start))


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


@router.get("/health")
async def health(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> HealthResponse:

    database, redis, ollama = await asyncio.gather(
        _run(check_database, settings), _run(check_redis, settings), _run(check_ollama, settings)
    )

    checks = {"database": database, "redis": redis, "ollama": ollama}

    healthy = all(check.status == "ok" for check in checks.values())

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "degraded", checks=checks)
