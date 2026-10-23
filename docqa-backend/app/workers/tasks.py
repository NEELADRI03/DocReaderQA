import os

from arq.connections import RedisSettings

async def ping(ctx:dict)->str:
    return "pong"

class WorkerSettings:
    functions = [ping]

    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))