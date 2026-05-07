# Email Context System — Design Document

**Project:** Backend Engineer Case Study — Ascend
**Stack:** Python 3.11+, FastAPI (async), SQLAlchemy 2.x, Pydantic v2, Postgres 16, Redis 7, Celery, Alembic
**Architecture style:** Modular monolith with separate Celery worker process

---

## 1. Problem statement

Multiple accountants in a CPA firm communicate with the same client. They lack visibility into each other's discussions, leading to redundant questions and poor coordination. Build an Email Context system that captures and summarizes all email discussions between any firm accountant and a specific client, providing a unified source of truth.

For the case study, real email ingestion (Microsoft Graph API) is replaced with a mock service backed by seeded data.

---

## 2. Functional requirements (locked)

1. One summary per client, aggregated across all email threads and all accountants who have ever emailed that client.
2. Clients can have multiple email addresses; an email address is unique within a firm.
3. Refresh re-runs the pipeline only when new emails exist since the last refresh; a `force=true` flag bypasses the conditional check.
4. Regular accountants see only the clients they are explicitly assigned to.
5. Auto-assignment is disabled. Email exchanges still flow into the summary content regardless of current assignment status.
6. Actors are extracted from both email headers (From, To, Cc) and email bodies, with a `source` field distinguishing the two.
7. Open action items track owner (or "unassigned") and the timestamp the item was raised.
8. Concluded discussions include resolution text and a timestamp of resolution.
9. Empty state: GET summary returns 404 if no summary exists yet for a client.
10. Firm Admin sees firm-level totals only (clients with summaries, total emails analyzed, last activity).
11. Superuser sees per-firm breakdown, paginated, sorted by firm name.

---

## 3. Non-functional requirements

| Pillar | Requirement |
|---|---|
| Readability | Type hints throughout, ruff + mypy clean, docstrings on services, sentence-cased naming |
| Modularity | Domain-oriented modules with service-layer interfaces; no cross-module repository imports |
| Scalability | Read/write DB split, async Celery workers, Redis cache, indexed queries, map-reduce summarization for large email sets, paginated reports |
| Security | JWT auth, bcrypt password hashing, AES-256-GCM at rest with key versioning, three-tier AuthZ (role → firm → assignment), tenant isolation in every query, no secrets in repo |
| Observability | Structured JSON logs with request IDs, Prometheus metrics endpoint, /health and /ready probes, refresh audit log |

---

## 4. High-level design (HLD)

### 4.1 Component overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          Clients                                 │
│   Accountant     │     Firm Admin     │      Superuser          │
└──────────────────┬──────────────────────────────────────────────┘
                   │ HTTPS + JWT bearer
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Gateway (TLS termination)                 │
└──────────────────┬──────────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI service (async)                         │
│  ┌─────────┬─────────┬──────────┬─────────┬─────────┐           │
│  │ Auth    │ Clients │ Summary  │ Jobs    │ Reports │           │
│  └─────────┴─────────┴──────────┴─────────┴─────────┘           │
└────┬─────────────────────────────────────────────────────────┬──┘
     │                                                         │
     ▼                                                         ▼
┌─────────────────┐    ┌────────────────────┐    ┌────────────────┐
│  Redis cluster   │    │  Celery worker     │    │  Postgres       │
│  - Cache         │◄───┤  process           │───►│  - Primary      │
│  - Celery broker │    │  - Refresh tasks   │    │  - Read replica │
│  - Job state     │    │  - Beat (cleanup)  │    │  (configurable) │
└─────────────────┘    └─────────┬──────────┘    └────────────────┘
                                 │
                                 ▼
                       ┌────────────────────┐
                       │   Gemini API       │
                       │   (structured JSON) │
                       └────────────────────┘
```

### 4.2 Why a modular monolith

This system is built as a single deployable unit organized into domain modules (`identity`, `clients`, `email_source`, `summarization`, `jobs`, `reporting`). Each module owns its tables, exposes a service-layer interface, and communicates with other modules only through those interfaces. This gives the modularity benefits of microservices — clear ownership, replaceable implementations, testability — without the operational overhead of inter-service communication, distributed tracing, and deploy coordination.

The Celery worker is the same codebase running as a separate process — a deployment topology choice, not a service decomposition.

### 4.3 Extraction path

If scale or organizational structure required it later, the cleanest extraction candidates are:
1. `summarization` — has an external dependency on Gemini, expensive operations, well-defined input/output
2. `email_source` — already abstracted behind an interface; biggest blast radius from external API changes

Service-layer interfaces are the seams along which extraction would happen. Replacing in-process calls with HTTP would not require changes to consumer code.

### 4.4 Read/write database split

The application reads far more than it writes. The session layer abstracts this:

| Operation | DB |
|---|---|
| GET endpoints | Read replica |
| POST /auth/login | Read replica |
| POST /summary/refresh | Enqueues only — no DB write in the API path |
| Celery worker (summarization writes) | Primary |
| Reports | Read replica |

Replication lag is not exposed to users on the refresh path because the cache (Redis) is updated by the worker on completion and is the source of truth for fresh reads.

---

## 5. Low-level design (LLD)

### 5.1 Folder structure

```
app/
├── main.py                    # FastAPI app, middleware, router registration
├── config.py                  # Pydantic Settings — all env vars
├── deps.py                    # FastAPI dependencies (db, current_user, role guards)
│
├── core/                      # Cross-cutting concerns
│   ├── security.py            # JWT encode/decode, password hashing
│   ├── encryption.py          # AES-256-GCM service with key versioning
│   ├── cache.py               # Redis client + helpers
│   ├── logging.py             # Structured JSON logging
│   └── exceptions.py          # Domain exceptions
│
├── db/
│   ├── base.py                # SQLAlchemy declarative base
│   ├── session.py             # Read/write session abstraction
│   └── migrations/            # Alembic
│
├── modules/                   # Domain modules
│   ├── identity/              # Firms, Accountants, auth
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── router.py
│   ├── clients/               # Clients, client_emails, assignments
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── router.py
│   ├── email_source/          # Mock + interface
│   │   ├── interface.py       # EmailSourceService ABC
│   │   ├── mock.py            # MockEmailService
│   │   └── models.py          # emails table
│   ├── summarization/         # The core pipeline
│   │   ├── models.py          # email_summaries, refresh_audit_log
│   │   ├── schemas.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   ├── gemini_client.py
│   │   ├── prompts.py
│   │   ├── tasks.py           # Celery tasks
│   │   └── router.py
│   ├── jobs/                  # Async job tracking
│   │   ├── models.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── router.py
│   └── reporting/
│       ├── service.py
│       └── router.py
│
├── workers/
│   ├── celery_app.py          # Celery instance, broker config
│   └── beat_schedule.py       # cleanup_expired_jobs schedule
│
└── observability/
    ├── middleware.py
    └── metrics.py

tests/
├── conftest.py
├── unit/
│   ├── test_encryption.py
│   ├── test_authz.py
│   └── test_summarization_service.py
└── integration/
    ├── test_auth_flow.py
    └── test_refresh_flow.py

scripts/
├── seed.py                    # Initial seed
├── add_new_emails.py          # Adds new emails for refresh demo
└── generate_keys.py           # Helper for AES key generation

docker-compose.yml
Dockerfile
.env.example
README.md
alembic.ini
pyproject.toml
docs/
└── DESIGN.md (this file)
```

### 5.2 Layered request flow — POST /summary/refresh

```
HTTP request
    │
    ▼
┌─────────────────────────────────────────┐
│ SummaryRouter (api/v1/summaries.py)     │
│ - Pydantic validation only              │
└────────────────┬────────────────────────┘
                 │ depends on:
                 │   get_current_user (JWT)
                 │   require_assigned_to_client
                 │   get_write_db
                 ▼
┌─────────────────────────────────────────┐
│ JobsService.enqueue_refresh()           │
│ - Insert row in jobs table (queued)     │
│ - Send Celery task with job_id          │
│ - Return job_id                         │
└────────────────┬────────────────────────┘
                 │ returns 202 + {job_id}
                 ▼
        Client polls GET /jobs/{id}

──── Meanwhile, in Celery worker process ────

Celery picks up task
    │
    ▼
┌─────────────────────────────────────────┐
│ SummarizationService.refresh_summary()  │
│ Pipeline:                               │
│  1. Acquire Postgres advisory lock       │
│  2. Compare email count vs stored count  │
│  3. If unchanged & not forced → skip     │
│  4. Else: fetch emails (chunk if large)  │
│  5. Map: summarize each chunk via Gemini │
│  6. Reduce: merge into final summary     │
│  7. Validate output schema (pydantic)    │
│  8. Encrypt payload (AES-GCM)            │
│  9. Upsert + audit log (single txn)      │
│  10. Update Redis cache                  │
│  11. Update job status → completed       │
└─────────────────────────────────────────┘
```

### 5.3 Module dependency rules

- Modules talk to each other only via `service.py` interfaces.
- No module imports another module's `repository.py` or `models.py` directly.
- Each module owns its tables; cross-module queries go through services.
- `core/` and `db/` are infrastructure and may be imported by any module.
- `deps.py` is the dependency-injection wiring layer; it imports services and produces FastAPI `Depends`-compatible callables.

---

## 6. Database schema

### 6.1 Entity relationship overview

```
firms ──────────────┐
  │                 │
  │ 1:N             │ 1:N
  ▼                 ▼
accountants    clients ───── 1:N ───► client_emails
  │                 │
  │ N:M (via assignments)
  ▼
accountant_client_assignments

clients ─── 1:N ──► emails
clients ─── 1:1 ──► email_summaries ─── 1:N ──► refresh_audit_log
                                                       ▲
                                                       │
accountants ──────────────────────────────────────────┘
                      (triggered_by)

jobs (independent — references client_id, accountant_id, retained 24h)
```

### 6.2 Table definitions

#### `firms`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| name | VARCHAR(255) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

#### `accountants`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| firm_id | UUID | NOT NULL, FK firms(id), INDEXED |
| email | VARCHAR(255) | NOT NULL, UNIQUE |
| full_name | VARCHAR(255) | NOT NULL |
| password_hash | VARCHAR(255) | NOT NULL |
| role | ENUM('accountant','admin','superuser') | NOT NULL DEFAULT 'accountant' |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

Composite index: `(firm_id, role)` for admin lookups.

#### `clients`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| firm_id | UUID | NOT NULL, FK firms(id), INDEXED |
| full_name | VARCHAR(255) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

#### `client_emails`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| client_id | UUID | NOT NULL, FK clients(id) ON DELETE CASCADE, INDEXED |
| email_address | VARCHAR(255) | NOT NULL, INDEXED |
| is_primary | BOOLEAN | NOT NULL DEFAULT FALSE |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

Constraints: `UNIQUE(client_id, email_address)`. Firm-level uniqueness of email addresses is enforced via a deferred unique index that joins through clients (or via application-level check on insert).

#### `accountant_client_assignments`

| Column | Type | Constraints |
|---|---|---|
| accountant_id | UUID | FK accountants(id), PART OF PK |
| client_id | UUID | FK clients(id), PART OF PK |
| assigned_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

Primary key: `(accountant_id, client_id)`. Indexes on both columns individually for lookup in either direction.

#### `emails` (mock data — would be replaced by Graph API in production)

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| client_id | UUID | NOT NULL, FK clients(id), INDEXED |
| sender_accountant_id | UUID | NULLABLE, FK accountants(id) |
| sender_email | VARCHAR(255) | NOT NULL |
| recipients | JSONB | NOT NULL — array of email strings |
| thread_id | VARCHAR(255) | NOT NULL, INDEXED |
| subject | VARCHAR(500) | NOT NULL |
| body | TEXT | NOT NULL |
| sent_at | TIMESTAMPTZ | NOT NULL, INDEXED |
| direction | ENUM('inbound','outbound') | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

Composite index: `(client_id, sent_at DESC)` for chronological retrieval.

#### `email_summaries`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| client_id | UUID | NOT NULL, FK clients(id), UNIQUE |
| firm_id | UUID | NOT NULL, FK firms(id), INDEXED |
| encrypted_payload | BYTEA | NOT NULL |
| encryption_nonce | BYTEA | NOT NULL |
| encryption_key_version | SMALLINT | NOT NULL |
| emails_analyzed_count | INTEGER | NOT NULL DEFAULT 0 |
| last_refreshed_at | TIMESTAMPTZ | NOT NULL |
| gemini_model_version | VARCHAR(64) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

The encrypted payload is a JSON document with structure:

```json
{
  "actors": [
    {"name": "Priya Sharma", "email": "priya@cpafirm.com",
     "source": "header", "role": "sender"},
    {"name": "Anita", "email": null,
     "source": "body", "role": "mentioned"}
  ],
  "concluded_discussions": [
    {"topic": "...", "resolution": "...",
     "resolved_at": "2025-03-15T10:30:00Z",
     "resolved_in_thread_id": "..."}
  ],
  "open_action_items": [
    {"item": "...", "owner": "John", "context": "...",
     "raised_at": "2025-03-20T14:00:00Z"}
  ]
}
```

#### `refresh_audit_log`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| summary_id | UUID | NOT NULL, FK email_summaries(id), INDEXED |
| triggered_by_accountant_id | UUID | NOT NULL, FK accountants(id) |
| triggered_at | TIMESTAMPTZ | NOT NULL DEFAULT now(), INDEXED |
| duration_ms | INTEGER | NULLABLE |
| emails_processed | INTEGER | NOT NULL DEFAULT 0 |
| status | ENUM('success','skipped_no_new_emails','failed') | NOT NULL |
| error_message | TEXT | NULLABLE |

#### `jobs`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| job_type | ENUM('refresh_summary') | NOT NULL |
| client_id | UUID | NULLABLE, FK clients(id), INDEXED |
| triggered_by_accountant_id | UUID | NOT NULL, FK accountants(id) |
| status | ENUM('queued','running','completed','failed','skipped') | NOT NULL DEFAULT 'queued' |
| result | JSONB | NULLABLE |
| error_message | TEXT | NULLABLE |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now(), INDEXED |
| started_at | TIMESTAMPTZ | NULLABLE |
| completed_at | TIMESTAMPTZ | NULLABLE |
| expires_at | TIMESTAMPTZ | NOT NULL, INDEXED |

A periodic Celery beat task (`cleanup_expired_jobs`) deletes rows where `expires_at < now()` every hour.

---

## 7. API endpoints

All endpoints are versioned under `/api/v1`. All endpoints (except `/auth/login`, `/health`, `/ready`, `/metrics`) require a valid JWT bearer token in the `Authorization` header.

### 7.1 GET endpoints

| Path | AuthZ | Response | Notes |
|---|---|---|---|
| `/health` | public | 200 if process is alive | Liveness probe |
| `/ready` | public | 200 if DB + Redis reachable | Readiness probe |
| `/metrics` | internal-only (network policy) | Prometheus exposition | |
| `/api/v1/clients` | accountant+ | List of clients accessible to the user. Regular accountants see only assigned clients. Admins see all firm clients. Superusers see all clients (paginated). | Supports `?page` and `?page_size` |
| `/api/v1/clients/{client_id}` | assigned+ | Single client with metadata (no summary content) | 404 if not accessible |
| `/api/v1/clients/{client_id}/summary` | assigned+ | Decrypted summary DTO (actors, concluded, open). Cache→read replica. | 404 if no summary exists |
| `/api/v1/jobs/{job_id}` | requester or admin/superuser | Job status, result location, timestamps | 404 if expired/unknown |
| `/api/v1/reports/firm` | admin (or superuser scoped to a firm via `?firm_id=...`) | Firm-level totals: clients with summaries, total emails analyzed, last activity | Cached 60s |
| `/api/v1/reports/global` | superuser | Per-firm breakdown, paginated | `?page`, `?page_size`, default 25 |

### 7.2 POST endpoints

| Path | AuthZ | Request body | Response | Notes |
|---|---|---|---|---|
| `/api/v1/auth/login` | public | `{email, password}` | `{access_token, token_type: "bearer", expires_in}` | Rate-limited (5 attempts/min/IP) |
| `/api/v1/auth/logout` | authenticated | none | 204 | Adds JTI to blocklist (Redis, TTL = remaining token life) |
| `/api/v1/clients/{client_id}/summary/refresh` | assigned+ | `{force?: boolean}` (optional) | 202 + `{job_id, status: "queued"}` | Enqueues Celery task. If `force=false` and no new emails since last refresh, the worker short-circuits and returns `status: "skipped_no_new_emails"` |

### 7.3 PUT endpoints

| Path | AuthZ | Request body | Response | Notes |
|---|---|---|---|---|
| `/api/v1/accountants/{id}/assignments` | admin | `{client_ids: [uuid, ...]}` | 200 + updated assignment list | Replaces all assignments for the accountant. Idempotent. |

### 7.4 PATCH endpoints

| Path | AuthZ | Request body | Response | Notes |
|---|---|---|---|---|
| `/api/v1/accountants/{id}` | self or admin | `{full_name?, is_active?}` | 200 + updated accountant | Cannot change `role` via this endpoint — separate admin-only action |

### 7.5 DELETE endpoints

| Path | AuthZ | Response | Notes |
|---|---|---|---|
| `/api/v1/accountants/{id}/assignments/{client_id}` | admin | 204 | Removes a single assignment |

Soft delete of clients/summaries/accountants is out of scope for the case study (per F13).

### 7.6 Endpoint-level error contract

| Status | Meaning |
|---|---|
| 400 | Invalid request body / query params (Pydantic validation failure) |
| 401 | Missing or invalid JWT |
| 403 | Authenticated but role insufficient (e.g., accountant calling admin endpoint) |
| 404 | Resource does not exist OR exists but caller cannot access it (enumeration-resistant) |
| 409 | Conflict (e.g., duplicate email on registration — out of scope for MVP) |
| 422 | Request validates structurally but fails business rule |
| 429 | Rate limit exceeded |
| 500 | Unhandled server error (log with request_id; client sees generic message) |
| 502 | Upstream Gemini failure after retries exhausted |
| 503 | Service degraded — DB or Redis unreachable |

---

## 8. Authorization matrix

Role permissions across resources. "self" means the caller is the resource being acted on.

| Resource | Accountant | Admin | Superuser |
|---|---|---|---|
| Own profile (read/update) | ✓ | ✓ | ✓ |
| Other accountants' profiles | — | ✓ (firm only) | ✓ |
| Clients (list) | Assigned only | All firm clients | All clients |
| Client summary (read) | Assigned only | All firm clients | All clients |
| Refresh summary | Assigned only | All firm clients | All clients |
| Manage assignments | — | ✓ (firm only) | ✓ |
| Firm report | — | ✓ (own firm) | ✓ (any firm) |
| Global report | — | — | ✓ |

Tenant isolation is enforced in every query by `firm_id` derived from the JWT (`accountant.firm_id`), never from the URL or request body.

---

## 9. Security model

### 9.1 Authentication
- JWT bearer tokens, HS256, 1-hour expiry
- Claims: `sub` (accountant id), `firm_id`, `role`, `iat`, `exp`, `jti`
- Passwords: bcrypt, work factor 12
- Login rate limit: 5 attempts/min/IP via slowapi

### 9.2 Authorization (composed via FastAPI Depends)
- `get_current_user` — decodes JWT, loads accountant, checks `is_active`
- `require_admin` — checks role ∈ {admin, superuser}
- `require_superuser` — checks role == superuser
- `require_assigned_to_client(client_id)` — checks assignment row exists OR role ∈ {admin (same firm), superuser}
- All "not authorized" responses return 404, not 403, when the resource exists but is out of scope (enumeration resistance)

### 9.3 Encryption at rest
- AES-256-GCM, application-level
- 32-byte key from environment, base64-encoded
- 12-byte random nonce per encryption (stored alongside ciphertext)
- `encryption_key_version` column supports rotation
- Production note: replace env-key with KMS envelope encryption (DEK per row, KEK in KMS)

### 9.4 Hygiene
- No secrets in repo (`.env.example` with placeholders)
- All SQL via SQLAlchemy ORM (parameterized)
- Sensitive fields redacted from logs (passwords, JWTs, encrypted payloads, decrypted summaries)
- Security headers via middleware: HSTS, X-Content-Type-Options, X-Frame-Options, CSP
- CORS strict allowlist via config
- Pydantic schemas with `extra="forbid"` to reject unknown fields

### 9.5 Auditability
Every refresh records who triggered it, when, duration, and outcome in `refresh_audit_log`.

---

## 10. Caching strategy

| Cache key | TTL | Invalidation trigger |
|---|---|---|
| `summary:client:{client_id}` | 1 hour | On successful refresh (worker writes fresh value) |
| `report:firm:{firm_id}` | 60 seconds | TTL only |
| `report:global:page:{n}:size:{m}` | 60 seconds | TTL only |
| `auth:blocklist:{jti}` | Remaining token life | On logout |

Stored format: JSON-serialized DTOs (decrypted). Redis must run on a private network with `requirepass` set; mention KMS-protected Redis cluster as a production hardening step in the README.

---

## 11. Summarization pipeline

### 11.1 Map-reduce for large email sets

When `len(emails) > CHUNK_THRESHOLD` (default 50):

1. **Map phase**: split emails into chunks of 50, sorted chronologically; summarize each chunk via Gemini
2. **Reduce phase**: feed the partial summaries into a final Gemini call that merges them
3. The merge prompt instructs the model to deduplicate actors, consolidate concluded topics, and union open action items

For sets at or below the threshold, single-call summarization is used.

### 11.2 Conditional refresh

On refresh:
1. Worker fetches current email count for client from `MockEmailService`
2. Compares to `email_summaries.emails_analyzed_count`
3. If equal AND not `force=true` → mark job `skipped`, do not call Gemini
4. Otherwise → run pipeline

### 11.3 Output schema (validated via Pydantic before encryption)

```python
class Actor(BaseModel):
    name: str
    email: EmailStr | None
    source: Literal["header", "body"]
    role: Literal["sender", "recipient", "cc", "mentioned"] | None

class ConcludedDiscussion(BaseModel):
    topic: str
    resolution: str
    resolved_at: datetime
    resolved_in_thread_id: str | None

class OpenActionItem(BaseModel):
    item: str
    owner: str  # name or "unassigned"
    context: str
    raised_at: datetime

class GeminiSummarySchema(BaseModel):
    actors: list[Actor]
    concluded_discussions: list[ConcludedDiscussion]
    open_action_items: list[OpenActionItem]
```

---

## 12. Observability

| Concern | Implementation |
|---|---|
| Logs | structlog JSON, request_id propagated via middleware |
| Metrics | Prometheus exposition at `/metrics`. Counters: `gemini_calls_total`, `gemini_failures_total`, `cache_hits_total`, `cache_misses_total`, `refresh_jobs_total{status=...}`. Histograms: request duration, gemini latency, summarization duration |
| Health | `/health` (process), `/ready` (DB ping + Redis ping) |
| Audit | `refresh_audit_log` for refresh provenance |

---

## 13. Deployment topology

`docker-compose.yml` services:

- `api` — FastAPI process (uvicorn)
- `worker` — Celery worker process (same image, different command)
- `beat` — Celery beat for periodic cleanup
- `postgres` — Primary DB
- `redis` — Cache + broker + result backend

Optional `postgres_replica` for demonstrating read/write split locally — wired in code, single-instance in compose by default.

---

## 14. Build sequence

| Order | Phase | Hours |
|---|---|---|
| 1 | Project skeleton + docker-compose (api, worker, postgres, redis) | 1.0 |
| 2 | Schema + Alembic migrations | 1.5 |
| 3 | Read/write session abstraction + DB dependencies | 0.5 |
| 4 | Encryption service (with unit tests) | 0.5 |
| 5 | Mock email service + seed script + add_new_emails.py | 1.5 |
| 6 | Auth (JWT, password hash, login endpoint) | 0.75 |
| 7 | AuthZ dependencies (current_user, role guards, assignment guard) | 0.75 |
| 8 | Gemini client (retry, timeout, structured output) | 1.0 |
| 9 | Summarization service (map-reduce, conditional, advisory lock) | 2.0 |
| 10 | Celery integration (task, jobs table, status endpoint) | 1.5 |
| 11 | Reporting service + endpoints | 1.0 |
| 12 | Caching layer (Redis) | 0.5 |
| 13 | Observability (logs, metrics, health/ready) | 0.75 |
| 14 | Tests, README, AI disclosure section, cleanup | 1.5 |
| | **Total** | **~12.5** |

---

## 15. What I'd add with more time

- Postgres Row-Level Security policies for tenant isolation at the DB layer
- KMS-backed envelope encryption (DEK per row, KEK in KMS)
- Refresh-token rotation flow
- Per-user rate limiting on refresh endpoint
- OpenTelemetry distributed tracing
- Real Microsoft Graph API integration behind the existing `EmailSourceService` interface
- Incremental summarization (merge old summary + new emails instead of full re-summarize)
- Summary versioning and diff view ("what changed since last refresh")
- Webhook notifications when refresh completes (instead of polling)
- Outbox pattern for reliable cache invalidation across replicas

---

## 16. AI disclosure

To be filled during development. Document:
- Which prompts produced useful boilerplate (models, migrations, test scaffolding)
- Where AI suggestions were rejected (and why)
- Manual decisions where AI was not consulted (architecture choices, security posture)
- Trade-offs that came from AI brainstorming
