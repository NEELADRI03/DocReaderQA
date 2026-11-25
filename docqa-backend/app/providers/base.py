from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class ProviderError(Exception):
    """A provider call failed: unreachable, an error reply, or a reply we can't use."""


class Embedder(Protocol):
    """Turns text into vectors. Documents and queries are embedded differently by some models."""

    @property
    def dim(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def aclose(self) -> None: ...


class LLMClient(Protocol):
    """Chat completion, streamed as text deltas."""

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...

    async def aclose(self) -> None: ...


async def complete(
    llm: LLMClient,
    messages: Sequence[ChatMessage],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """The whole answer at once, for short calls like query rewriting."""
    deltas = llm.stream(messages, temperature=temperature, max_tokens=max_tokens)
    return "".join([delta async for delta in deltas])
