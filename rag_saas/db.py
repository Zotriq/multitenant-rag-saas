"""Database access. Every tenant request runs inside a transaction scoped with SET LOCAL app.tenant_id."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from contextlib import contextmanager
from importlib import resources
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def migrate(admin_url: str, dim: int) -> None:
    """Create tables, RLS policies and the rag_app role. Run with an admin/owner connection."""
    sql = resources.files("rag_saas").joinpath("schema.sql").read_text().replace("{dim}", str(dim))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql)


def create_tenant(admin_url: str, name: str) -> tuple[uuid.UUID, str]:
    """Create a tenant and return (tenant_id, api_key). The key is shown once; only its hash is stored."""
    api_key = "rag_" + secrets.token_urlsafe(32)
    with psycopg.connect(admin_url) as conn:
        tenant_id = conn.execute("INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,)).fetchone()[0]
        conn.execute(
            "INSERT INTO api_keys (key_hash, tenant_id, label) VALUES (%s, %s, 'default')",
            (hash_key(api_key), tenant_id),
        )
    return tenant_id, api_key


class Store:
    """Application data access, connecting as the low-privilege rag_app role."""

    def __init__(self, app_url: str):
        self.app_url = app_url

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.app_url, row_factory=dict_row) as conn:
            register_vector(conn)
            yield conn

    def tenant_for_key(self, api_key: str) -> uuid.UUID | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT tenant_id FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL", (hash_key(api_key),)
            ).fetchone()
        return row["tenant_id"] if row else None

    @contextmanager
    def tenant(self, tenant_id: uuid.UUID) -> Iterator[psycopg.Connection]:
        """A transaction in which RLS only exposes this tenant's rows."""
        with self._conn() as conn:
            with conn.transaction():
                conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                yield conn

    # --- tenant-scoped operations (no tenant_id in WHERE clauses: RLS adds it) ---

    def add_document(self, tenant_id: uuid.UUID, title: str, source: str | None,
                     chunks: list[str], embeddings: list[list[float]]) -> uuid.UUID:
        import numpy as np

        with self.tenant(tenant_id) as conn:
            doc_id = conn.execute(
                "INSERT INTO documents (title, source) VALUES (%s, %s) RETURNING id", (title, source)
            ).fetchone()["id"]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, content, embedding) VALUES (%s, %s, %s, %s)",
                    [(doc_id, i, c, np.array(e, dtype=np.float32)) for i, (c, e) in enumerate(zip(chunks, embeddings))],
                )
        return doc_id

    def list_documents(self, tenant_id: uuid.UUID) -> list[dict]:
        with self.tenant(tenant_id) as conn:
            return conn.execute(
                "SELECT d.id, d.title, d.source, d.created_at, count(c.id) AS chunks "
                "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
                "GROUP BY d.id ORDER BY d.created_at DESC"
            ).fetchall()

    def delete_document(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> bool:
        with self.tenant(tenant_id) as conn:
            return conn.execute("DELETE FROM documents WHERE id = %s", (document_id,)).rowcount == 1

    def search(self, tenant_id: uuid.UUID, embedding: list[float], top_k: int = 5) -> list[dict]:
        import numpy as np

        with self.tenant(tenant_id) as conn:
            return conn.execute(
                "SELECT c.content, c.chunk_index, d.id AS document_id, d.title, "
                "       1 - (c.embedding <=> %(q)s) AS score "
                "FROM chunks c JOIN documents d ON d.id = c.document_id "
                "ORDER BY c.embedding <=> %(q)s LIMIT %(k)s",
                {"q": np.array(embedding, dtype=np.float32), "k": top_k},
            ).fetchall()
