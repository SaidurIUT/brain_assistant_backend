"""
LightRAG service — cloud-LLM, in-process orchestration.

Query and ingest both go to DeepSeek's OpenAI-compatible Chat Completions API
(via LightRAG's openai_complete_if_cache). Embeddings use BAAI's bge-m3 served
locally by Ollama (1024-dim, multilingual). The dual-model split that the old
codebase used (qwen 9b for ingest, qwen 0.8b for query) is collapsed — DeepSeek
Flash is capable enough for LightRAG's strict-JSON entity extraction and fast
enough for per-query answer generation, so a single LLM_MODEL setting covers
both paths. Bump to a stronger DeepSeek model via env if entity extraction
quality slips.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import numpy as np
import ollama as ollama_client

from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of a confidence-gated query.

    answer is None when no relevant context was found — caller should hand off
    to a human instead of speaking on behalf of an empty knowledge base.
    """

    answer: str | None
    confident: bool
    chunk_count: int


def _evaluate_retrieval(data_result: dict[str, Any] | None) -> int:
    """Pure: count chunks returned by aquery_data. Returns 0 on any failure shape."""
    if not isinstance(data_result, dict) or data_result.get("status") != "success":
        return 0
    chunks = data_result.get("data", {}).get("chunks") or []
    return len(chunks)


_EMBED_DIM = 1024  # bge-m3 output dimension

# Customer-support formatting instructions injected as the user_prompt on every
# query. Keeps replies clean for a chat widget — direct answer, short
# paragraphs, no LightRAG-style "### Answer" / "### References" headers leaking
# through to customers.
_CUSTOMER_SUPPORT_PROMPT = """\
You are a customer support assistant. Reply directly to the customer using ONLY
the provided context.

Formatting rules:
- Lead with the answer in the first 1-2 sentences.
- Keep paragraphs short (2-3 sentences).
- Use bullet points when listing items, steps, or options.
- Do not include section headers like "### Answer", "### References", or
  "### Content & Grounding".
- Do not list source document names at the end.
- Do not say "based on the context" or "according to the documents" — answer
  naturally as if you are the company speaking to the customer.
- If the context doesn't cover the question, say so in one short sentence
  without apologizing repeatedly.

Tone: warm, concise, professional. Match the level of formality the customer
is using. Avoid filler phrases."""


async def _llm_complete(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    """Bridge LightRAG's llm_model_func contract to DeepSeek's OpenAI-compatible API."""
    return await openai_complete_if_cache(
        settings.llm_model,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        **kwargs,
    )


def _configure_pg_env() -> None:
    """Derive POSTGRES_* env vars from DATABASE_URL for LightRAG's ClientManager."""
    raw = settings.database_url
    clean = raw.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    parsed = urlparse(clean)
    os.environ.setdefault("POSTGRES_HOST", parsed.hostname or "localhost")
    os.environ.setdefault("POSTGRES_PORT", str(parsed.port or 5432))
    os.environ.setdefault("POSTGRES_USER", parsed.username or "postgres")
    os.environ.setdefault("POSTGRES_PASSWORD", parsed.password or "")
    os.environ.setdefault("POSTGRES_DATABASE", parsed.path.lstrip("/"))
    os.environ.setdefault("POSTGRES_WORKSPACE", "brain_assistant")
    os.environ.setdefault("POSTGRES_MAX_CONNECTIONS", "10")


async def _embed(texts: list[str]) -> np.ndarray:
    """bge-m3 embedding via Ollama on the office PC. 1024-dim, multilingual."""
    client = ollama_client.AsyncClient(host=settings.ollama_base_url)
    response = await client.embed(
        model=settings.embed_model,
        input=texts,
        keep_alive="30m",  # keep the model warm between queries
    )
    return np.array(response.embeddings)


def _make_rag() -> LightRAG:
    _configure_pg_env()
    os.makedirs(settings.lightrag_working_dir, exist_ok=True)
    return LightRAG(
        working_dir=settings.lightrag_working_dir,
        kv_storage="PGKVStorage",
        vector_storage="PGVectorStorage",
        graph_storage="NetworkXStorage",
        doc_status_storage="PGDocStatusStorage",
        llm_model_func=_llm_complete,
        llm_model_name=settings.llm_model,
        embedding_func=EmbeddingFunc(
            embedding_dim=_EMBED_DIM,
            max_token_size=8192,
            func=_embed,
        ),
        vector_db_storage_cls_kwargs={
            "cosine_better_than_threshold": settings.rag_retrieval_threshold,
        },
    )


async def query(question: str) -> str:
    """Fast query path — DeepSeek Flash answer generation against retrieved chunks."""
    rag = _make_rag()
    await rag.initialize_storages()
    try:
        result = await rag.aquery(
            question,
            param=QueryParam(
                mode="naive",
                enable_rerank=False,
                user_prompt=_CUSTOMER_SUPPORT_PROMPT,
            ),
        )
        return result or ""
    finally:
        await rag.finalize_storages()


async def query_with_confidence(question: str) -> QueryResult:
    """Probe retrieval before paying for LLM generation.

    aquery_data returns the retrieved chunks without running the answer model.
    If nothing clears the configured cosine threshold we skip the LLM entirely
    and signal handoff — saving latency and avoiding ungrounded replies.
    """
    rag = _make_rag()
    await rag.initialize_storages()
    try:
        probe_param = QueryParam(mode="naive", enable_rerank=False)
        data_result = await rag.aquery_data(question, param=probe_param)
        chunk_count = _evaluate_retrieval(data_result)
        if chunk_count < settings.rag_min_chunks_for_answer:
            return QueryResult(answer=None, confident=False, chunk_count=chunk_count)

        answer = await rag.aquery(
            question,
            param=QueryParam(
                mode="naive",
                enable_rerank=False,
                user_prompt=_CUSTOMER_SUPPORT_PROMPT,
            ),
        )
        return QueryResult(answer=answer or "", confident=True, chunk_count=chunk_count)
    finally:
        await rag.finalize_storages()


async def ingest(text: str) -> None:
    """Slow ingest path — entity extraction via DeepSeek Flash."""
    rag = _make_rag()
    await rag.initialize_storages()
    try:
        await rag.ainsert(text)
    finally:
        await rag.finalize_storages()


def sync_query(question: str) -> str:
    """Blocking wrapper for Celery workers."""
    return asyncio.run(query(question))


def sync_query_with_confidence(question: str) -> QueryResult:
    """Blocking wrapper for Celery workers."""
    return asyncio.run(query_with_confidence(question))


def sync_ingest(text: str) -> None:
    """Blocking wrapper for Celery workers."""
    asyncio.run(ingest(text))
