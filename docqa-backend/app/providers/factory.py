from app.config import Settings
from app.providers.base import Embedder, LLMClient
from app.providers.ollama import OllamaEmbedder, OllamaLLMClient


def create_embedder(settings: Settings) -> Embedder:
    match settings.embedding_provider:
        case "ollama":
            return OllamaEmbedder(
                base_url=settings.ollama_base_url,
                model=settings.embedding_model,
                dim=settings.embedding_dim,
                document_prefix=settings.embedding_document_prefix,
                query_prefix=settings.embedding_query_prefix,
            )


def create_llm_client(settings: Settings) -> LLMClient:
    match settings.llm_provider:
        case "ollama":
            return OllamaLLMClient(
                base_url=settings.ollama_base_url,
                model=settings.llm_model,
                reasoning_effort=settings.llm_reasoning_effort,
                timeout=settings.llm_timeout_seconds,
            )
