# Email Context System

Backend implementation for the Ascend email context case study. It is a modular FastAPI monolith with a separate Celery worker process, Postgres persistence, Redis cache/broker, encrypted summaries, seeded mock email ingestion, and role/tenant-aware APIs.

## What is included

- FastAPI app under `app/` with `identity`, `clients`, `email_source`, `summarization`, `jobs`, and `reporting` modules.
- SQLAlchemy 2 async models, read/write session abstraction, and Alembic initial migration.
- JWT login, bcrypt password hashing, logout blocklist, admin/superuser guards, and assignment-based client access.
- Mock email source backed by seeded rows, with the Microsoft Graph replacement isolated behind `EmailSourceService`.
- Conditional refresh pipeline with Postgres advisory locks, map-reduce summarization, Pydantic validation, AES-256-GCM encryption, refresh audit log, Redis cache updates, and Celery job tracking.
- Firm and global reports with short Redis TTLs.
- Health, readiness, Prometheus metrics, structured JSON logging, request IDs, and security headers.

## Quick start

With `make`:

```powershell
make setup
make db-up
make migrate-up
make seed
make stack-up
```

Or with raw commands:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api python scripts/seed.py
docker compose up api worker beat
```

The API runs at `http://localhost:8000`.

## Demo logins

After seeding, all demo users use password `password123`.

- `admin@ascendcpa.co` - firm admin
- `alex@ascendcpa.co` - accountant assigned to Acme Manufacturing
- `maya@ascendcpa.co` - accountant assigned to Acme Manufacturing and Bright Dental Group
- `superuser@platformmail.co` - platform superuser

## Example flow

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/auth/login `
  -ContentType application/json `
  -Body '{"email":"alex@ascendcpa.co","password":"password123"}'

$headers = @{ Authorization = "Bearer $($login.access_token)" }
$clients = Invoke-RestMethod -Uri http://localhost:8000/api/v1/clients -Headers $headers
$clientId = $clients.items[0].id

Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/clients/$clientId/summary/refresh" `
  -Headers $headers `
  -ContentType application/json `
  -Body '{"force":true}'
```

Poll the returned job:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/jobs/<job_id>" -Headers $headers
```

Then read the summary:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/clients/$clientId/summary" -Headers $headers
```

## Development

```powershell
make setup
make check
```

For a full local stack, prefer Docker Compose because Postgres and Redis are required for the complete refresh/job/cache behavior.

## Migrations

```powershell
make migrate-up     # alembic upgrade head
make migrate-down   # alembic downgrade -1
```

## Environment notes

- `USE_MOCK_GEMINI=true` keeps the app runnable without an external API key. Set it to `false` and provide `GEMINI_API_KEY` to call Gemini.
- `ENCRYPTION_KEYS_JSON` stores base64-encoded 32-byte AES keys by key version. Use `python scripts/generate_keys.py` for a new key.
- The Docker Compose file uses a single Postgres instance for read and write URLs, but the code supports separate read replica configuration.

## AI disclosure

This implementation was generated with AI assistance from the supplied design document. The architecture, module boundaries, security requirements, and endpoint contract were driven by the provided spec. AI-generated boilerplate was accepted for repetitive scaffolding, migrations, DTOs, and tests, then adjusted for tenant isolation, encrypted payload handling, async job flow, and local demo ergonomics. External-service behavior defaults to a deterministic mock summarizer so the case study remains runnable without secrets.
