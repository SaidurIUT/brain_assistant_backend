"""
LightRAG service — in-process, with separate models for ingest vs query.

LightRAG's entity-extraction prompts need a capable model (9b) — small models
hallucinate the JSON structure or hang. But query-time answer generation only
needs to read the retrieved context and produce a short reply, which a tiny
model (0.8b) handles in seconds.

So we use two configurations against the same storage:
  - INGEST_MODEL → qwen3.5:9b (slow, infrequent, runs in /knowledge/ingest)
  - QUERY_MODEL  → qwen3.5:0.8b (fast, runs on every customer message)

Both share the same postgres tables and the same NetworkX graph file, so a
document ingested with 9b is queryable with 0.8b.
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
from lightrag.llm.ollama import ollama_model_complete
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

_EMBED_DIM = 768  # nomic-embed-text output dimension


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
    """Raw Ollama embedding — bypasses lightrag's ollama_embed which hardcodes dim=1024."""
    client = ollama_client.AsyncClient(host=settings.ollama_base_url)
    response = await client.embed(
        model=settings.embed_model,
        input=texts,
        keep_alive="30m",  # keep embed model in VRAM between queries
    )
    return np.array(response.embeddings)


def _make_rag(llm_model: str) -> LightRAG:
    _configure_pg_env()
    os.makedirs(settings.lightrag_working_dir, exist_ok=True)
    return LightRAG(
        working_dir=settings.lightrag_working_dir,
        kv_storage="PGKVStorage",
        vector_storage="PGVectorStorage",
        graph_storage="NetworkXStorage",
        doc_status_storage="PGDocStatusStorage",
        llm_model_func=ollama_model_complete,
        llm_model_name=llm_model,
        llm_model_kwargs={
            "host": settings.ollama_base_url,
            "options": {"num_ctx": 4096},
            "keep_alive": "30m",  # keep model in VRAM so we don't pay cold-load on every query
        },
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
    """Fast query path — uses small model for answer generation."""
    rag = _make_rag(settings.query_llm_model)
    await rag.initialize_storages()
    try:
        result = await rag.aquery(
            question, param=QueryParam(mode="naive", enable_rerank=False)
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
    rag = _make_rag(settings.query_llm_model)
    await rag.initialize_storages()
    try:
        param = QueryParam(mode="naive", enable_rerank=False)
        data_result = await rag.aquery_data(question, param=param)
        chunk_count = _evaluate_retrieval(data_result)
        if chunk_count < settings.rag_min_chunks_for_answer:
            return QueryResult(answer=None, confident=False, chunk_count=chunk_count)

        answer = await rag.aquery(question, param=param)
        return QueryResult(answer=answer or "", confident=True, chunk_count=chunk_count)
    finally:
        await rag.finalize_storages()


async def ingest(text: str) -> None:
    """Slow ingest path — uses capable model for entity extraction."""
    rag = _make_rag(settings.ingest_llm_model)
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
