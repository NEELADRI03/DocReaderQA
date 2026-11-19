import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.config import Settings
from app.main import app

client = TestClient(app)


async def ok(settings: Settings) -> None:
    return None


async def down(settings: Settings) -> None:
    raise ConnectionError("connection refused")


@pytest.fixture(autouse=True)
def all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Swap out the real checks, so the tests don't need Postgres, Redis or Ollama
    monkeypatch.setattr(health, "check_database", ok)
    monkeypatch.setattr(health, "check_redis", ok)
    monkeypatch.setattr(health, "check_ollama", ok)


def test_health_ok_when_all_checks_pass() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {name: check["status"] for name, check in body["checks"].items()} == {
        "database": "ok",
        "redis": "ok",
        "ollama": "ok",
    }


def test_health_503_when_one_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "check_redis", down)

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"]["status"] == "error"
    assert body["checks"]["redis"]["error"] == "connection refused"
    assert body["checks"]["database"]["status"] == "ok"


def test_slow_check_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hangs(settings: Settings) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(health, "check_ollama", hangs)

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["checks"]["ollama"]["error"] == "TimeoutError"
