# Multi-Tenancy in Brain Assistant

How the backend isolates one business's data from another's — what a tenant is, where its identity lives, and how that identity flows through every code path.

## TL;DR

- One **`Company` row** = one **tenant**.
- The tenant's UUID is `companies.id`.
- That same UUID is used **everywhere**: every tenant-scoped table FKs to it, and LightRAG's `workspace` column stores it as a string. One identifier, one mental model.
- Tenant identity travels two paths: **request-driven** (admin uploading docs via API) and **event-driven** (customer messaging Chatwoot widget).
- LightRAG isolates tenant data via its `workspace` column — every read and write is filtered by `WHERE workspace = $company_id`, so a query for tenant A literally cannot return tenant B's chunks at the SQL layer.

## What "tenant" means here

A tenant is **one business using the product**. Acme Corp is a tenant. NFS Solutions is a tenant. Each has its own:

- Knowledge base (their docs, their crawled pages)
- Brand settings (logo, colors, assistant name)
- Chatwoot connection(s) (which inboxes their AgentBot is attached to)
- Conversations (their customers' messages)
- Members (the humans who admin or use the workspace)

Tenants are isolated by design — Acme's bot only answers from Acme's content; an NFS customer never sees Acme's data.

## The identity layer

```
User (one human)
   │ M:N via CompanyMember
   ▼
Company (one tenant)
   │
   ├─ BrandSettings        (1:1)
   ├─ ChatwootConnection   (1:N — one per inbox)
   ├─ CompanyUpload + KnowledgeDocument + BackgroundJob
   ├─ WebsiteCrawlJob + WebsiteCrawlCandidate
   └─ ApiServer/Endpoint/DocumentationSource
```

| Concept | Where it lives | Type |
|---|---|---|
| Tenant identity | `companies.id` | `UUID` (primary key) |
| User ↔ tenant link | `company_members` | `UUID` FK both ways, plus a `role` |
| Tenant-scoped data | `*.company_id` on every tenant table | `UUID` FK to `companies.id` |
| LightRAG isolation | `lightrag_*.workspace` | `String` containing the same UUID |

**A user can belong to multiple companies** (`CompanyMember` is a many-to-many junction). Every authenticated endpoint either picks the user's default workspace or accepts `?company_id=<uuid>` to scope explicitly.

## How tenants get created

Tenants appear **lazily at first touch**, not at registration. The flow:

1. User registers via `POST /api/v1/auth/register` — creates a `User` row. No company yet.
2. User makes the first request that needs a workspace (e.g. `GET /api/v1/settings`).
3. The `current_company(db, user)` dependency runs:
   - Looks up the user's `CompanyMember` rows.
   - If none exist, calls `create_default_workspace(user)` which inserts:
     - One `Company` row (name = "Untitled company", admin = the user)
     - One `BrandSettings` row (defaults)
     - One `CompanyMember` row linking user ↔ company with `role='administrator'`
   - Returns the Company.

So every authenticated user has at least one Company by the time they touch any endpoint that scopes by tenant. New companies thereafter would be created by other flows (member invites, multi-workspace admin actions).

## How tenant identity flows at runtime

There are two routes through the backend; each picks up the tenant in a different way.

### Path A — Admin request (uploading a doc, configuring brand, etc.)

```
HTTP request with ?company_id=<uuid> (or default)
       │
       ▼
Endpoint dependency: current_company(db, user, company_id)
       │  (verifies user has CompanyMember row for that Company)
       ▼
   `company` in scope
       │
       ▼
Endpoint passes company.id into downstream services:
   await rag_service.ingest(text, company.id)
   create_document_extraction_job(db, upload=record)   # carries upload.company_id
```

The endpoint never trusts client-supplied `company_id` blindly — `current_company` checks the user actually belongs to that workspace. If not, 404.

### Path B — Customer webhook (customer messages, bot replies)

```
Chatwoot AgentBot fires webhook to /api/v1/webhooks/chatwoot/agent-bot
       │
       │  Payload includes account_id + inbox_id (Chatwoot's IDs, not ours)
       ▼
Webhook handler stores the event in chatwoot_events, queues a Celery task
       │
       ▼
process_chatwoot_event worker runs:
   _resolve_connection(db, account_id, inbox_id)
       │
       ├──► Looks up chatwoot_connections WHERE
       │      chatwoot_account_id=X AND chatwoot_inbox_id=Y AND status='active'
       │
       ├──► If a row matches: returns dict including company_id from that row
       │
       └──► If no row matches (dev only): falls back to env vars
              (requires CHATWOOT_FALLBACK_COMPANY_ID — see "Dev fallback" below)
       │
       ▼
   connection["company_id"] in scope
       │
       ▼
sync_query_with_confidence(question, connection["company_id"])
       │
       ▼
RAG runs scoped to that tenant's workspace.
```

The webhook never receives an explicit `company_id` from the network — Chatwoot doesn't know about our tenants. Instead, the **`chatwoot_connections` row is the lookup table**: it bridges Chatwoot's identity space (account+inbox) to ours (company_id). Adding multi-platform adapters later (Teams, Discord) follows the same pattern — a per-platform `*_connections` table maps platform identity → `company_id`.

## How LightRAG isolates per-tenant data

LightRAG is a third-party library that creates its own tables in our postgres (prefixed `lightrag_*`). Every one of those tables has a `workspace VARCHAR` column. Every read and write LightRAG performs filters by that column:

```sql
SELECT content
FROM lightrag_doc_chunks
WHERE workspace = $1   -- ← per-tenant filter, baked into every query
ORDER BY content_vector <=> $query_embedding
LIMIT 20;
```

In `app/services/rag_service.py:_make_rag(company_id)`, we pass `workspace=str(company_id)` to the `LightRAG(...)` constructor:

```python
def _make_rag(company_id: UUID) -> LightRAG:
    workspace = str(company_id)
    return LightRAG(
        working_dir=settings.lightrag_working_dir,
        workspace=workspace,   # ← scopes every storage operation
        ...
    )
```

LightRAG then carries that workspace on every internal storage backend (`chunks_vdb`, `entities_vdb`, `relationships_vdb`, NetworkX graph) and uses it as the filter on every SQL query and as the subdirectory for the local graph file:

```
lightrag_storage/
├── <company-A-uuid>/
│   └── graph_chunk_entity_relation.graphml
└── <company-B-uuid>/
    └── graph_chunk_entity_relation.graphml
```

So **tenant isolation in the AI layer is just "pass the right workspace string."** No application-layer post-filtering, no row-level security tricks — LightRAG's existing schema does the work.

### Why no foreign key?

LightRAG's `workspace` is `VARCHAR`, not `UUID`, and has no foreign key to `companies(id)`. This is **LightRAG's choice** (it's a generic library — different users may key on slugs, integers, ULIDs). The relationship is enforced in **our code**, at the single chokepoint `rag_service._make_rag(company_id: UUID)`. As long as all writes to LightRAG flow through this typed function, no garbage workspace can be created. This is the same pattern Stripe, Slack, and most cloud-service integrations use — application-layer enforcement, not DB-level.

## Dev fallback — `CHATWOOT_FALLBACK_COMPANY_ID`

The webhook worker has a fallback for when no `chatwoot_connections` row matches an incoming event. This exists **only because the frontend UI for creating connection rows (part of US-03) isn't fully shipped yet**. In production it should be empty.

```env
# .env (dev only)
CHATWOOT_FALLBACK_COMPANY_ID=<your-dev-company-uuid>
```

When set, the env-var fallback path in `_resolve_connection` claims every incoming message belongs to this one Company. **Single-tenant by design** — it's a developer convenience, not a multi-tenant feature. Once admins can self-serve Chatwoot connections via the UI, remove the env var (leave it empty) so the fallback returns `None` and forces real connection rows.

## Quick reference

### Find your Company UUID

```bash
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d brain_assistant_backend \
  -c "SELECT id, name, created_at FROM companies ORDER BY created_at;"
```

### Count chunks per tenant in LightRAG

```bash
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d brain_assistant_backend \
  -c "SELECT workspace, COUNT(*) FROM lightrag_doc_chunks GROUP BY workspace;"
```

### Inspect a tenant's Chatwoot connections

```sql
SELECT company_id, chatwoot_base_url, chatwoot_account_id, chatwoot_inbox_id, status
FROM chatwoot_connections
WHERE company_id = '<your-uuid>';
```

### Verify tenant isolation end-to-end

1. Create two companies (e.g. via two registrations).
2. Upload different content to each (via the dashboard, scoped by `?company_id=`).
3. Confirm each company's `chatwoot_events.reply_content` only references their own content.

## Known limitations / future work

| Limitation | Impact | Mitigation |
|---|---|---|
| LLM response cache (`lightrag_llm_cache`) auto-scopes by workspace, **but** cache is not invalidated on KB updates | Stale answers after re-ingest | [Task #13 — Invalidate LLM cache on ingest] |
| `chatwoot_fallback_company_id` is a single-tenant dev hack | Multi-tenant dev testing requires real `chatwoot_connections` rows or env-var swapping | Build admin endpoint or UI for connection creation (part of US-03 finish) |
| Workspace is a string in LightRAG, not FK-enforced | A bug in our code could write garbage workspace strings | All writes funnel through `rag_service` with typed `company_id: UUID`. Add an assertion if paranoid. |
| No row-level security in the auth/membership layer | A SQL-injection or buggy ORM query could leak | Pydantic + SQLAlchemy parameterization closes the practical risk; consider Postgres RLS as future hardening |
| Tenant-scoped settings (confidence threshold, system prompt) are global env vars | Can't tune per-tenant yet | US-21 (workspace settings) and US-14 (system prompt) — both backlog items |

## Glossary

- **Tenant** — One business using the product. Same as "workspace" or "company" in everyday speech.
- **Company** — The database model holding tenant identity. Created lazily on first authenticated request.
- **Workspace** — Two meanings depending on context: (1) human-facing word for a Company; (2) the `workspace` column LightRAG uses for filtering. We use the company's UUID as the workspace value, so they're equivalent in our setup.
- **CompanyMember** — Junction table linking a User to a Company with a role. Lets one user admin multiple tenants.
- **`chatwoot_connections`** — The bridge from Chatwoot's identity (account+inbox) to our tenant (company_id). One row per inbox we serve.
