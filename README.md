# Brain Assistant Backend

FastAPI backend for Brain Assistant — an AI customer-support layer that sits on top of [Chatwoot](https://www.chatwoot.com/). Admins onboard a workspace, connect their Chatwoot inbox, feed in knowledge (uploaded files, scraped pages, or full website crawls), and the backend then answers customer messages from that knowledge — handing off to a human when retrieval confidence is low.

The service runs as a FastAPI app plus a Celery worker. Knowledge ingestion and retrieval are powered by [LightRAG](https://github.com/HKUDS/LightRAG) with pgvector storage and Ollama-served LLMs.

## Ports

This service deliberately avoids the existing workspace ports listed in the root README.

- FastAPI: `8010`
- Backend Postgres host port: `55432`
- Backend database name: `brain_assistant_backend`
- Dev email is delivered through the Brain Assistant backend Mailhog only:
  - SMTP host port: `1125`
  - Web UI: `8125`
  - Open the inbox at http://localhost:8125. Port `1125` is SMTP only and will not render in a browser.

## Local Run With Docker

```sh
cd backend
cp .env.example .env
docker compose up --build
```

This starts the backend Postgres database, the backend-only Mailhog service, runs Alembic migrations, and serves FastAPI on http://localhost:8010.
It also starts Redis and one `brain-worker` Celery worker for background jobs such as Knowledge Base document text extraction.

Swagger/OpenAPI documentation is available after the API starts:

- Swagger UI: http://localhost:8010/docs
- ReDoc: http://localhost:8010/redoc
- OpenAPI JSON: http://localhost:8010/openapi.json

## Keycloak Auth Mode

The backend defaults to local email/password auth. To use Keycloak for onboarding and dashboard auth, set matching backend and frontend environment variables:

```text
AUTH_PROVIDER=keycloak
KEYCLOAK_BASE_URL=http://localhost:8080
KEYCLOAK_REALM=brain-assistant
KEYCLOAK_CLIENT_ID=brain-assistant-onboarding
```

In `onboarding-web/.env`, set:

```text
NEXT_PUBLIC_AUTH_PROVIDER=keycloak
NEXT_PUBLIC_KEYCLOAK_BASE_URL=http://localhost:8080
NEXT_PUBLIC_KEYCLOAK_REALM=brain-assistant
NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=brain-assistant-onboarding
```

Configure the Keycloak client as a public OIDC client with standard authorization code flow, PKCE, web origin `http://localhost:3010`, and redirect URI `http://localhost:3010/auth/keycloak/callback`.

Scale extraction workers up to the local maximum of five when processing many Knowledge Base uploads:

```sh
cd backend
docker compose up --scale brain-worker=5
```

If the database is already running because you started it separately, use:

```sh
cd backend
docker compose up --build brain-assistant-api
```

## Local Run Without Docker API

Only use this path if you want to run FastAPI directly on your machine. The active Python environment must have the backend dependencies installed first.

```sh
cd backend
python -m pip install -e ".[dev]"
docker compose up -d brain-assistant-db brain-assistant-mailhog brain-assistant-redis
python -m alembic upgrade head
python -m fastapi dev app/main.py --host 0.0.0.0 --port 8010
```

Run a local worker in a second terminal if you use the direct API path:

```sh
cd backend
REDIS_URL=redis://localhost:56379/0 python -m celery -A app.jobs.celery_app:celery_app worker --loglevel=info --concurrency=1 -Q brain-jobs
```

## Auth Flow

- Register with any valid email address.
- Registration creates a default company workspace, administrator membership, and brand settings record, then sends an email verification link.
- Users can continue onboarding before verification, but member invitations are blocked until email verification is completed.
- `POST /api/v1/auth/verify-email` verifies the email token and starts the first session.
- Login returns a short-lived access token and sets a refresh token in an HttpOnly cookie.
- Refresh tokens are opaque, stored hashed in Postgres, rotated on every refresh, and revoked on reuse.
- Logout revokes the current refresh session.
- Logout-all revokes every active session for the user.
- Administrators invite members from settings; invited people receive an email and set their first password through `POST /api/v1/auth/accept-invitation`.

## Chatbot Pipeline

Customer messages flow Chatwoot → backend → Chatwoot, all over HTTP. The backend never touches Chatwoot's database.

1. Chatwoot delivers an AgentBot webhook to `POST /api/v1/webhooks/chatwoot/agent-bot`. The handler verifies the HMAC signature, deduplicates by delivery id, and writes a `chatwoot_events` row.
2. A Celery task picks up the event, resolves the matching `chatwoot_connections` row for the inbox, fetches the last 8 messages from Chatwoot for conversational context, and sends a typing-on indicator.
3. The worker calls `rag_service.query_with_confidence`, which probes LightRAG retrieval first (cheap, no LLM). One of four outcomes is posted back to the conversation:

   | Outcome | When | Customer-facing reply |
   |---|---|---|
   | **answer** | retrieval cleared the confidence threshold | LightRAG-generated grounded answer |
   | **handoff** | zero chunks cleared the threshold | "I'm not certain about that — let me get a teammate to help." |
   | **fallback** | LLM returned empty despite context | "Thanks for your message. I will get back to you shortly." |
   | **failure** | LLM/Ollama unreachable after retries | "I'm having trouble answering right now. A team member will follow up." |

4. The reply is stored in `chatwoot_events.reply_content` and a structured log line records `confident`, `chunks`, `outcome` per event so the threshold can be tuned against real traffic.

A local-dev fallback exists: if no `chatwoot_connections` row matches, the worker reads `CHATWOOT_*` env vars instead. This is single-tenant and only suitable for the first developer's local setup.

## Knowledge Base & Ingestion

Three input paths reach the same RAG index. Each runs as a Celery background job and writes a `knowledge_documents` row that progresses through `queued → processing → ingesting → completed` (or `failed`).

### 1. File uploads (US-08)

`POST /api/v1/uploads/documents` with a PDF, DOCX, Markdown, plain text, or CSV file. A `document_text_extraction` job extracts text, then calls `rag_service.sync_ingest`. Scanned PDFs without selectable text are marked failed (OCR is intentionally out of scope for this phase).

### 2. Single-page web scrape (US-07)

`POST /api/v1/knowledge/web-pages` with a URL. A `single_page_web_scrape` job uses Playwright (headless Chromium) to render the page, strips `script/style/nav/footer/form` etc., and ingests the cleaned text. Pages that render no readable text (login walls, empty SPAs) skip ingest and complete cleanly.

### 3. Full website crawl (US-07)

`POST /api/v1/knowledge/crawls` with a root URL and either a list of category IDs (`policy`, `pricing`, `docs`, etc.) or a free-form prompt ("only pages about returns"). A `website_crawl_discovery` job parses sitemaps + does BFS link discovery, optionally classifies URLs via the configured LLM, and writes one `website_crawl_candidates` row per discovered URL.

Admin then reviews the candidates and selects which URLs to actually scrape via `POST /api/v1/knowledge/crawls/{id}/queue-pages`. Selected URLs are queued as individual `single_page_web_scrape` jobs and feed the same ingest path as #2.

### Background workers

Two Celery workers run different queues:

- **Webhook worker** (`app.workers.celery_app`): handles Chatwoot events. Fast-turnaround, high concurrency.
- **Jobs worker** (`app.jobs.celery_app`, queue `brain-jobs`): runs ingestion. `--concurrency=1` because LightRAG entity extraction is GPU-bound and serializes well.

### LightRAG runtime

The backend uses LightRAG in-process with a dual-model strategy:

- **Ingest model** (`INGEST_LLM_MODEL`, default `qwen3.5:9b`) for entity extraction — slow, capable, infrequent.
- **Query model** (`QUERY_LLM_MODEL`, default `qwen3.5:0.8b`) for answer generation — fast, runs on every customer message.

Both share the same pgvector tables and a local NetworkX graph file under `LIGHTRAG_WORKING_DIR`. Embeddings use `nomic-embed-text` (768-dim).

Confidence gating is tunable via `RAG_RETRIEVAL_THRESHOLD` (cosine floor, default `0.3`) and `RAG_MIN_CHUNKS_FOR_ANSWER` (default `1`).

### Multi-tenancy caveat

`companies.id` (UUID) is the tenant identifier and is foreign-keyed by every tenant-scoped table (`company_uploads`, `knowledge_documents`, `chatwoot_connections`, `background_jobs`, etc.). **LightRAG's vector index and graph file are not yet partitioned by `company_id`** — they all share one workspace. This is a known issue scheduled to be fixed before any real second customer is onboarded.

## Email Modes

Development uses Mailhog:

```text
MAIL_MODE=dev
SMTP_HOST=localhost
SMTP_PORT=1125
```

When the API runs inside Docker, `backend/docker-compose.yml` starts its own `brain-assistant-mailhog` service and points `SMTP_HOST` to that container. It does not use the Chatwoot Mailhog service.

Production requires real SMTP credentials:

```text
MAIL_MODE=production
MAIL_FROM=Brain Assistant <support@example.com>
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_STARTTLS=true
```

## Settings Flow

- `GET /api/v1/settings` returns the current user, selected company, brand settings, members, and the user's active workspaces.
- Pass `company_id` to settings routes to manage or view a specific workspace when the user belongs to more than one organization.
- `PATCH /api/v1/settings/user` changes first and last name.
- `PATCH /api/v1/settings/company` changes company details.
- `PATCH /api/v1/settings/brand` changes whitelabel/brand details.
- `POST /api/v1/settings/members` adds a workspace member with `administrator`, `manager`, `agent`, or `viewer` role.
- `PATCH /api/v1/settings/members/{id}/role` changes a member role.
