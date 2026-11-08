-- Multi-tenant RAG schema. {dim} is replaced with the embedding size at migration time.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash    text PRIMARY KEY,               -- sha256 of the key; the key itself is never stored
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    label       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz
);

CREATE TABLE IF NOT EXISTS documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE
                DEFAULT NULLIF(current_setting('app.tenant_id', true), '')::uuid,
    title       text NOT NULL,
    source      text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           bigserial PRIMARY KEY,
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE
                 DEFAULT NULLIF(current_setting('app.tenant_id', true), '')::uuid,
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  int NOT NULL,
    content      text NOT NULL,
    embedding    vector({dim}) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_tenant_idx ON chunks (tenant_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS documents_tenant_idx ON documents (tenant_id);

-- Row-level security: the database itself refuses to show or change another tenant's rows,
-- even if application code forgets a WHERE clause.
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON documents;
CREATE POLICY tenant_isolation ON documents
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation ON chunks;
CREATE POLICY tenant_isolation ON chunks
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- The API connects as this role. It must NOT be a superuser or table owner with BYPASSRLS.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
        CREATE ROLE rag_app LOGIN PASSWORD 'rag_app' NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO rag_app;
GRANT SELECT ON tenants, api_keys TO rag_app;
GRANT SELECT, INSERT, DELETE ON documents, chunks TO rag_app;
GRANT USAGE ON SEQUENCE chunks_id_seq TO rag_app;
