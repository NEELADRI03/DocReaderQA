import json
from collections.abc import Callable

import httpx2
import pytest

from app.config import Settings
from app.providers.base import ChatMessage, Embedder, LLMClient, ProviderError, complete
from app.providers.factory import create_embedder, create_llm_client
from app.providers.ollama import OllamaEmbedder, OllamaLLMClient
from tests.fakes import FakeEmbedder, FakeLLMClient

pytestmark = pytest.mark.anyio

BASE_URL = "http://ollama.test:11434"
QUESTION = [ChatMessage(role="user", content="Hi?")]

Handler = Callable[[httpx2.Request], httpx2.Response]


def embedder(handler: Handler, dim: int = 3) -> OllamaEmbedder:
    return OllamaEmbedder(
        base_url=BASE_URL,
        model="nomic-embed-text",
        dim=dim,
        document_prefix="search_document: ",
        query_prefix="search_query: ",
        transport=httpx2.MockTransport(handler),
    )


def llm(handler: Handler) -> OllamaLLMClient:
    return OllamaLLMClient(
        base_url=BASE_URL, model="qwen3:8b", transport=httpx2.MockTransport(handler)
    )


def embeddings_reply(*vectors: list[float]) -> httpx2.Response:
    # Reversed on purpose: the client must order the vectors by index
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)][::-1]
    return httpx2.Response(200, json={"object": "list", "data": data})


def sse(*chunks: dict[str, object]) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def delta(**fields: str) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": None}]}


# --- The fakes stand in for the real providers --------------------------------


async def test_fakes_satisfy_the_interfaces() -> None:
    # mypy checks these assignments against the Protocols
    fake_embedder: Embedder = FakeEmbedder(dim=4)
    fake_llm: LLMClient = FakeLLMClient(["a", "b"])

    [vector] = await fake_embedder.embed_documents(["chunk"])
    assert len(vector) == fake_embedder.dim == 4
    assert await fake_embedder.embed_query("chunk") == vector
    assert await complete(fake_llm, QUESTION) == "ab"


# --- Factory: providers come from config ---------------------------------------


def test_factory_builds_ollama_from_settings() -> None:
    settings = Settings(embedding_dim=1024)  # type: ignore[call-arg]

    built_embedder = create_embedder(settings)
    assert isinstance(built_embedder, OllamaEmbedder)
    assert built_embedder.dim == 1024
    assert isinstance(create_llm_client(settings), OllamaLLMClient)


# --- OllamaEmbedder -------------------------------------------------------------


async def test_embed_documents_uses_the_openai_endpoint_and_prefix() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return embeddings_reply([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

    vectors = await embedder(handler).embed_documents(["first", "second"])

    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert requests[0].url == f"{BASE_URL}/v1/embeddings"
    assert json.loads(requests[0].content) == {
        "model": "nomic-embed-text",
        "input": ["search_document: first", "search_document: second"],
    }


async def test_embed_query_uses_the_query_prefix() -> None:
    sent: list[object] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content)["input"])
        return embeddings_reply([0.0, 0.0, 1.0])

    assert await embedder(handler).embed_query("what?") == [0.0, 0.0, 1.0]
    assert sent == [["search_query: what?"]]


async def test_embed_nothing_makes_no_request() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request expected")

    assert await embedder(handler).embed_documents([]) == []


async def test_wrong_dimension_is_an_error() -> None:
    client = embedder(lambda request: embeddings_reply([1.0, 0.0]), dim=3)

    with pytest.raises(ProviderError, match="returned 2 dimensions, but EMBEDDING_DIM is 3"):
        await client.embed_query("x")


async def test_embedding_error_reply_is_a_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"error": {"message": "model 'x' not found"}})

    with pytest.raises(ProviderError, match="404: model 'x' not found"):
        await embedder(handler).embed_query("x")


async def test_unreachable_ollama_is_a_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError, match="ConnectError"):
        await embedder(handler).embed_query("x")


# --- OllamaLLMClient ------------------------------------------------------------


async def test_stream_yields_content_and_skips_thinking_and_usage() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return sse(
            delta(role="assistant", content="", reasoning="Let me think"),
            delta(content="Hello"),
            delta(content=" there"),
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        )

    deltas = [d async for d in llm(handler).stream(QUESTION, max_tokens=50)]

    assert deltas == ["Hello", " there"]
    assert requests[0].url == f"{BASE_URL}/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["messages"] == [{"role": "user", "content": "Hi?"}]
    assert payload["stream"] is True
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == 50


async def test_max_tokens_is_left_out_by_default() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        payloads.append(json.loads(request.content))
        return sse(delta(content="ok"))

    assert await complete(llm(handler), QUESTION) == "ok"
    assert "max_tokens" not in payloads[0]


async def test_chat_error_reply_is_a_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"error": {"message": "model 'qwen3:8b' not found"}})

    with pytest.raises(ProviderError, match="404: model 'qwen3:8b' not found"):
        await complete(llm(handler), QUESTION)


async def test_error_in_the_middle_of_the_stream_is_a_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return sse(delta(content="Hel"), {"error": {"message": "model runner crashed"}})

    with pytest.raises(ProviderError, match="model runner crashed"):
        await complete(llm(handler), QUESTION)
