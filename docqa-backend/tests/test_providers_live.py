import os
from collections.abc import AsyncIterator

import pytest

from app.config import Settings
from app.providers.base import ChatMessage, Embedder, LLMClient, complete
from app.providers.factory import create_embedder, create_llm_client

# Talks to a real Ollama with the models pulled. CI has none, so these only run on request.
pytestmark = pytest.mark.anyio


@pytest.fixture
def settings() -> Settings:
    url = os.environ.get("TEST_OLLAMA_URL")
    if not url:
        pytest.skip("TEST_OLLAMA_URL not set")
    return Settings(ollama_base_url=url)  # type: ignore[call-arg]


@pytest.fixture
async def embedder(settings: Settings) -> AsyncIterator[Embedder]:
    client = create_embedder(settings)
    yield client
    await client.aclose()


@pytest.fixture
async def llm(settings: Settings) -> AsyncIterator[LLMClient]:
    client = create_llm_client(settings)
    yield client
    await client.aclose()


async def test_embedding_size_matches_config(embedder: Embedder) -> None:
    vectors = await embedder.embed_documents(["The cat sat on the mat.", "Tax rates for 2026."])
    query = await embedder.embed_query("Where did the cat sit?")

    assert [len(v) for v in vectors] == [embedder.dim, embedder.dim]
    assert len(query) == embedder.dim


async def test_llm_streams_an_answer(llm: LLMClient) -> None:
    question = [ChatMessage(role="user", content="Reply with the single word: pong")]

    deltas = [d async for d in llm.stream(question, temperature=0, max_tokens=20)]

    assert len(deltas) >= 1
    assert "pong" in "".join(deltas).lower()


async def test_complete_joins_the_stream(llm: LLMClient) -> None:
    question = [ChatMessage(role="user", content="What is 2 + 2? Reply with the number only.")]

    assert "4" in await complete(llm, question, temperature=0, max_tokens=10)
