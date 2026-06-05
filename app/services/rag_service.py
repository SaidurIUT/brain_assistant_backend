"""
LightRAG service — cloud-LLM, in-process, tenant-scoped.

Each rag_service call takes a company_id (the tenant identity). The UUID is
stringified and passed as LightRAG's `workspace` so the underlying postgres
tables (and NetworkX graph files) automatically isolate per-tenant data —
LightRAG filters every read and write by `WHERE workspace = $1`, so a query
for tenant A never sees tenant B's chunks.

Query and ingest both go to DeepSeek's OpenAI-compatible Chat Completions API
(via LightRAG's openai_complete_if_cache). Embeddings use BAAI's bge-m3 served
locally by Ollama (1024-dim, multilingual). Bump LLM_MODEL via env if entity
extraction quality slips.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

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


_INSUFFICIENT_ANSWER_RE = re.compile(
    r"don.t have (enough|any|sufficient)|"
    r"no (relevant |available )?information|"
    r"cannot (find|answer|provide)|"
    r"(not able|unable) to (find|answer|provide)|"
    r"not (enough|sufficient|covered)|"
    r"no relevant (content|context|data)",
    re.IGNORECASE,
)


def _is_insufficient_answer(answer: str) -> bool:
    """True when the LLM signals it couldn't answer from the retrieved context.

    Two paths:
      - LightRAG appends "[no-context]" when zero chunks were retrieved.
        This marker is deterministic so we trust it without a length guard.
      - Otherwise we match common 'I can't answer' phrases, gated by a
        length cap to prevent false positives in real substantive replies
        that mention a gap mid-answer.
    """
    if "[no-context]" in answer.lower():
        return True
    return bool(_INSUFFICIENT_ANSWER_RE.search(answer)) and len(answer.strip()) < 250


def _evaluate_retrieval(data_result: dict[str, Any] | None) -> int:
    """Pure: count chunks returned by aquery_data. Returns 0 on any failure shape."""
    if not isinstance(data_result, dict) or data_result.get("status") != "success":
        return 0
    chunks = data_result.get("data", {}).get("chunks") or []
    return len(chunks)


_EMBED_DIM = 1024  # bge-m3 output dimension

# Built-in default user_prompt used when a tenant hasn't supplied their own
# via the /api/v1/system-prompt API (US-14). Mirrors
# app.services.system_prompts.DEFAULT_SYSTEM_PROMPT — they're intentionally
# the same string so the API can return the exact text the bot would use.
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
    """Derive POSTGRES_* connection env vars from DATABASE_URL for LightRAG's
    shared connection pool. Note: workspace is NOT set here — we pass it
    explicitly per call via LightRAG's `workspace=` kwarg so concurrent
    requests for different tenants can't race on a global value.
    """
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


def _make_rag(company_id: UUID) -> LightRAG:
    """Build a LightRAG instance scoped to one tenant.

    The company_id (UUID) is stringified and passed as `workspace=`, which
    LightRAG uses to filter every storage read/write by `workspace` column —
    SQL-level tenant isolation with no extra application logic.
    """
    _configure_pg_env()
    os.makedirs(settings.lightrag_working_dir, exist_ok=True)
    return LightRAG(
        working_dir=settings.lightrag_working_dir,
        workspace=str(company_id),
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


async def query(
    question: str, company_id: UUID, system_prompt_override: str | None = None
) -> str:
    """Fast query path — DeepSeek Flash answer generation against tenant chunks.

    If system_prompt_override is provided, it replaces the built-in customer
    support prompt entirely. Caller is expected to resolve it from the tenant's
    custom prompt (or None to use the default).
    """
    rag = _make_rag(company_id)
    user_prompt = system_prompt_override or _CUSTOMER_SUPPORT_PROMPT
    await rag.initialize_storages()
    try:
        result = await rag.aquery(
            question,
            param=QueryParam(
                mode="naive",
                enable_rerank=False,
                user_prompt=user_prompt,
            ),
        )
        return result or ""
    finally:
        await rag.finalize_storages()


async def query_with_confidence(
    question: str,
    company_id: UUID,
    system_prompt_override: str | None = None,
    search_query: str | None = None,
) -> QueryResult:
    """Single-pass confidence-gated query — one embed + one vector search.

    Previously called aquery_data (embed + search) then aquery (embed + search
    + LLM), paying for two Ollama round-trips per message. Now uses a single
    aquery call. The cosine threshold still filters low-relevance chunks at the
    DB level. _is_insufficient_answer catches the case where no useful chunks
    were found and the LLM signals it can't answer.

    search_query kept for API compatibility but unused — aquery handles
    retrieval and generation in one pass.
    """
    rag = _make_rag(company_id)
    user_prompt = system_prompt_override or _CUSTOMER_SUPPORT_PROMPT
    await rag.initialize_storages()
    try:
        answer = await rag.aquery(
            question,
            param=QueryParam(
                mode="naive",
                enable_rerank=False,
                user_prompt=user_prompt,
            ),
        )
        answer = answer or ""
        if _is_insufficient_answer(answer):
            return QueryResult(answer=None, confident=False, chunk_count=0)
        return QueryResult(answer=answer, confident=True, chunk_count=1)
    finally:
        await rag.finalize_storages()


async def ingest(text: str, company_id: UUID) -> None:
    """Slow ingest path — entity extraction via DeepSeek Flash, scoped to tenant."""
    rag = _make_rag(company_id)
    await rag.initialize_storages()
    try:
        await rag.ainsert(text)
    finally:
        await rag.finalize_storages()


async def ingest_document(text: str, company_id: UUID, *, doc_id: str, file_path: str) -> None:
    """Insert or reinsert one source document with a deterministic LightRAG id."""
    rag = _make_rag(company_id)
    await rag.initialize_storages()
    try:
        await rag.ainsert(text, ids=doc_id, file_paths=file_path)
    finally:
        await rag.finalize_storages()


async def delete_document(doc_id: str, company_id: UUID) -> None:
    """Delete one deterministic document id from LightRAG, ignoring not-found results."""
    rag = _make_rag(company_id)
    await rag.initialize_storages()
    try:
        result = await rag.adelete_by_doc_id(doc_id)
        if getattr(result, "status", "") not in {"success", "not_found"}:
            logger.warning("LightRAG delete returned %s for %s", getattr(result, "status", ""), doc_id)
    finally:
        await rag.finalize_storages()


_HANDOFF_SUMMARY_SYSTEM_PROMPT = """\
You are writing a brief handoff note for a human customer support agent.
The AI bot could not find a relevant answer for the customer.

Summarise in 2-3 sentences what the customer needs help with, based only
on the conversation below. Be factual and concise. Write in third person
(e.g. "The customer is asking about...").
Do not mention "knowledge base", "AI", or "bot"."""


async def summarise_for_handoff(history: list[dict], customer_message: str) -> str:
    """Generate an LLM summary of the conversation for the agent's private note.

    Returns empty string on any failure so the caller can fall back to the
    template note without the agent ever seeing an error.
    """
    turns = []
    for msg in history:
        speaker = "Customer" if msg["sender"] == "contact" else "Assistant"
        turns.append(f"{speaker}: {msg['content']}")
    turns.append(f"Customer: {customer_message}")

    try:
        result = await _llm_complete(
            "\n".join(turns),
            system_prompt=_HANDOFF_SUMMARY_SYSTEM_PROMPT,
        )
        return (result or "").strip()
    except Exception:
        logger.warning("summarise_for_handoff: LLM call failed, falling back to template")
        return ""


def sync_query(
    question: str, company_id: UUID, system_prompt_override: str | None = None
) -> str:
    """Blocking wrapper for Celery workers."""
    return asyncio.run(query(question, company_id, system_prompt_override))


def sync_query_with_confidence(
    question: str,
    company_id: UUID,
    system_prompt_override: str | None = None,
    search_query: str | None = None,
) -> QueryResult:
    """Blocking wrapper for Celery workers."""
    return asyncio.run(query_with_confidence(question, company_id, system_prompt_override, search_query))


def sync_summarise_for_handoff(history: list[dict], customer_message: str) -> str:
    """Blocking wrapper for Celery workers."""
    return asyncio.run(summarise_for_handoff(history, customer_message))


def sync_ingest(text: str, company_id: UUID) -> None:
    """Blocking wrapper for Celery workers."""
    asyncio.run(ingest(text, company_id))


def sync_ingest_document(text: str, company_id: UUID, *, doc_id: str, file_path: str) -> None:
    """Blocking wrapper for deterministic source-document ingest."""
    asyncio.run(ingest_document(text, company_id, doc_id=doc_id, file_path=file_path))


def sync_delete_document(doc_id: str, company_id: UUID) -> None:
    """Blocking wrapper for deterministic source-document deletion."""
    asyncio.run(delete_document(doc_id, company_id))
