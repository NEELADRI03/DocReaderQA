import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

import httpx2

from app.providers.base import ChatMessage, ProviderError

ReasoningEffort = Literal["none", "low", "medium", "high"]


def _client(
    base_url: str, timeout: float, transport: httpx2.AsyncBaseTransport | None
) -> httpx2.AsyncClient:
    # Ollama's OpenAI-compatible API lives under /v1
    return httpx2.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/v1", timeout=timeout, transport=transport
    )


def _error_message(response: httpx2.Response) -> str:
    # OpenAI-style errors look like {"error": {"message": "..."}}
    try:
        return f"{response.status_code}: {response.json()['error']['message']}"
    except (ValueError, KeyError, TypeError):
        return f"{response.status_code}: {response.text[:200]}"


class OllamaEmbedder:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        document_prefix: str = "",
        query_prefix: str = "",
        timeout: float = 60.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._dim = dim
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix
        self._http = _client(base_url, timeout, transport)

    @property
    def dim(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed([self._document_prefix + text for text in texts])

    async def embed_query(self, text: str) -> list[float]:
        [vector] = await self._embed([self._query_prefix + text])
        return vector

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []

        try:
            response = await self._http.post(
                "/embeddings", json={"model": self._model, "input": inputs}
            )
        except httpx2.HTTPError as exc:
            raise ProviderError(f"embedding request failed: {exc!r}") from exc
        if response.is_error:
            raise ProviderError(f"embedding request failed: {_error_message(response)}")

        try:
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            vectors: list[list[float]] = [row["embedding"] for row in rows]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"unexpected embedding response: {exc!r}") from exc

        if len(vectors) != len(inputs):
            raise ProviderError(f"sent {len(inputs)} texts, got {len(vectors)} vectors")
        # A wrong size would only fail later, when the vector is written to VECTOR(n)
        for vector in vectors:
            if len(vector) != self._dim:
                raise ProviderError(
                    f"{self._model} returned {len(vector)} dimensions, "
                    f"but EMBEDDING_DIM is {self._dim}"
                )
        return vectors


class OllamaLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        reasoning_effort: ReasoningEffort = "none",
        timeout: float = 300.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._http = _client(base_url, timeout, transport)

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "temperature": temperature,
            "reasoning_effort": self._reasoning_effort,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            async with self._http.stream("POST", "/chat/completions", json=payload) as response:
                if response.is_error:
                    await response.aread()
                    raise ProviderError(f"chat request failed: {_error_message(response)}")

                async for event in httpx2.EventSource(response):
                    if event.data == "[DONE]":
                        return
                    for delta in _content_deltas(event.data):
                        yield delta
        except httpx2.HTTPError as exc:
            raise ProviderError(f"chat request failed: {exc!r}") from exc

    async def aclose(self) -> None:
        await self._http.aclose()


def _content_deltas(data: str) -> list[str]:
    try:
        chunk = json.loads(data)
    except ValueError as exc:
        raise ProviderError(f"unexpected chat chunk: {data[:200]}") from exc
    if "error" in chunk:
        raise ProviderError(f"chat stream failed: {chunk['error']}")

    # Thinking arrives in delta.reasoning and is skipped; the last chunk only carries usage
    return [
        choice["delta"]["content"]
        for choice in chunk.get("choices", [])
        if choice.get("delta", {}).get("content")
    ]
