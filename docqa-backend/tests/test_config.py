import pytest
from pydantic import ValidationError

from app.config import Settings


def test_cors_origins_splits_commas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://example.com")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.cors_origins == ["http://localhost:5173", "http://example.com"]


def test_wrong_type_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_DIM", "not-a-number")

    with pytest.raises(ValidationError, match="embedding_dim"):
        Settings()  # type: ignore[call-arg]


def test_missing_required_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")

    with pytest.raises(ValidationError, match="database_url"):
        Settings()  # type: ignore[call-arg]


def test_jwt_secret_is_hidden_when_printed() -> None:
    settings = Settings()  # type: ignore[call-arg]

    assert "test-secret" not in repr(settings)
