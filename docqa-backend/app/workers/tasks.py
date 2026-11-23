from typing import Any

from arq.connections import RedisSettings

from app.config import get_settings


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


class WorkerSettings:
    functions = [ping]

    # redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
