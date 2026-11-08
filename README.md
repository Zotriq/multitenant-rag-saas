# Multi-tenant RAG SaaS

![tests](https://github.com/Zotriq/multitenant-rag-saas/actions/workflows/tests.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Security](https://img.shields.io/badge/isolation-row--level%20security-success?style=flat-square)

The backend for a **"chat with your documents" SaaS** where many companies share one database, and
**each company can only ever see its own documents**.

Most RAG demos have one user and one document set. Real SaaS products have hundreds of customers, and one
leaked document ends the business. Here, isolation is enforced by **PostgreSQL row-level security**, so even
a bug in the application code can't return another tenant's data.

## How isolation works

```
request ──► X-API-Key ──► sha256 lookup ──► tenant_id
                                               │
            BEGIN;  SET LOCAL app.tenant_id = '<tenant_id>';      ← scoped to this transaction only
            SELECT ... FROM chunks ORDER BY embedding <=> $q;     ← no tenant filter in app code
                                               │
            PostgreSQL RLS policy:  USING (tenant_id = current_setting('app.tenant_id'))
                                               │
                         only this tenant's rows exist, as far as the query can tell
```

- The API connects as `rag_app`, a role that **cannot bypass RLS**: not a superuser and no `BYPASSRLS`.
- `FORCE ROW LEVEL SECURITY` means the policy applies even to the table owner.
- `WITH CHECK` stops a tenant from *writing* rows that claim to belong to someone else.
- With no tenant set, every query returns **zero rows** (it fails closed).
- API keys are stored as **SHA-256 hashes only** and shown once when a tenant is created.
- Deleting another tenant's document returns `404`, the same as a missing one, so IDs can't be probed.

## Features

- Upload **PDF, Markdown or text** files (or raw text). Documents are chunked along paragraph and sentence boundaries with overlap.
- **pgvector HNSW index** for fast cosine-similarity search.
- Answers with **numbered citations** (document title, chunk, similarity score, excerpt).
- Says **"I don't know"** when nothing relevant is found, instead of making something up.
- **Admin endpoint** to create tenants and API keys.
- **Runs fully offline** with no API key (hashing embeddings + extractive answers) for demos and tests, or with OpenAI embeddings and GPT for production.
- Docker Compose with the official `pgvector/pgvector:pg16` image.

## API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/admin/tenants` | `X-Admin-Token` | Create a tenant; returns its API key once |
| `POST` | `/documents` | `X-API-Key` | Upload a file (`file`) or text (`text`, `title`) |
| `GET` | `/documents` | `X-API-Key` | List this tenant's documents with chunk counts |
| `DELETE` | `/documents/{id}` | `X-API-Key` | Delete a document and its chunks |
| `POST` | `/query` | `X-API-Key` | `{"question": "...", "top_k": 5}` → answer + citations |

```bash
curl -X POST localhost:8000/query -H "X-API-Key: rag_..." -H "Content-Type: application/json" \
     -d '{"question": "What is our refund policy for retainers?"}'
```

Example response shape (with OpenAI enabled):

```json
{
  "answer": "Retainers are refundable within 30 days [1].",
  "citations": [
    {"n": 1, "title": "Retainer policy", "chunk_index": 0, "score": 0.83, "excerpt": "Acme Law retainer policy. ..."}
  ]
}
```

## Run it

```bash
git clone https://github.com/Zotriq/multitenant-rag-saas.git
cd multitenant-rag-saas
cp .env.example .env            # add OPENAI_API_KEY for real embeddings, or leave empty for offline mode
docker compose up --build       # Postgres + pgvector, migrations, API on :8000

curl -X POST localhost:8000/admin/tenants -H "X-Admin-Token: change-me" \
     -H "Content-Type: application/json" -d '{"name": "Acme Law"}'
```

Without Docker:

```bash
pip install -e .
python -m rag_saas migrate
python -m rag_saas create-tenant "Acme Law"
uvicorn rag_saas.api:app_from_env --factory --reload
```

## Tests

10 tests run against a **real PostgreSQL + pgvector database**. Most of them try to break isolation:

- Tenant B asks a question only tenant A's document answers, and gets nothing from A.
- Tenant B tries to delete tenant A's document using its real ID, and gets `404` with nothing deleted.
- A **direct database connection** as the app role, with **no WHERE clause**, sees zero rows without a tenant and zero rows as another tenant.
- Inserting a row that claims to be another tenant's is rejected by the database.
- The app role is verified to have no superuser or `BYPASSRLS` privilege.
- Plus auth, uploads (PDF/MD/TXT validation), the "I don't know" path and chunking.

```bash
pip install -e ".[dev]"
PG_ADMIN_URL=postgresql://postgres@localhost:5432/rag_test pytest
```

## Project structure

```
rag_saas/
  schema.sql     tables, pgvector HNSW index, RLS policies, rag_app role
  db.py          migrations, tenant creation, tenant-scoped transactions, search
  api.py         FastAPI endpoints and API-key auth
  chunking.py    paragraph/sentence chunking with overlap
  providers.py   OpenAI embeddings + answers, and offline fallbacks
tests/           isolation and API tests (real PostgreSQL)
```

## License

MIT © Zohaib Tariq
