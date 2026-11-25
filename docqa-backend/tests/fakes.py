import hashlib
from collections.abc import AsyncIterator, Sequence

from app.providers.base import ChatMessage


class FakeEmbedder:
    """Same text, same vector, with no model. Records what it was asked to embed."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim
        self.documents: list[str] = []
        self.queries: list[str] = []

    @property
    def dim(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self._vector(text)

    async def aclose(self) -> None:
        pass

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255 for i in range(self._dim)]


class FakeLLMClient:
    """Streams a scripted reply. Records the messages of every call."""

    def __init__(self, reply: Sequence[str] = ("Hello", ", ", "world")) -> None:
        self._reply = list(reply)
        self.calls: list[list[ChatMessage]] = []

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        for delta in self._reply:
            yield delta

    async def aclose(self) -> None:
        pass
