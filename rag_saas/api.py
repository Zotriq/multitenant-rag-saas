"""Multi-tenant RAG API. Each request is authenticated by API key, which decides the tenant."""

from __future__ import annotations

import io
import os
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .chunking import chunk_text
from .db import Store, create_tenant
from .providers import Embedder, Generator

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MIN_SCORE = 0.15


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)


class Citation(BaseModel):
    n: int
    document_id: uuid.UUID
    title: str
    chunk_index: int
    score: float
    excerpt: str


class QueryOut(BaseModel):
    answer: str
    citations: list[Citation]


class TenantIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


def _read_upload(file: UploadFile, data: bytes) -> str:
    name = (file.filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    raise HTTPException(415, "Upload a .pdf, .txt or .md file")


def create_app(store: Store, embedder: Embedder, generator: Generator, *, admin_url: str, admin_token: str) -> FastAPI:
    app = FastAPI(title="Multi-tenant RAG API", version="0.1.0")

    def current_tenant(x_api_key: str | None = Header(default=None)) -> uuid.UUID:
        tenant = store.tenant_for_key(x_api_key) if x_api_key else None
        if tenant is None:
            raise HTTPException(401, "Missing or invalid X-API-Key")
        return tenant

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/admin/tenants", status_code=201)
    def new_tenant(body: TenantIn, x_admin_token: str | None = Header(default=None)) -> dict:
        if not admin_token or x_admin_token != admin_token:
            raise HTTPException(403, "Admin token required")
        tenant_id, api_key = create_tenant(admin_url, body.name)
        return {"tenant_id": tenant_id, "api_key": api_key, "note": "Store this key now; it is not shown again."}

    @app.post("/documents", status_code=201)
    async def upload(file: UploadFile | None = File(None), title: str | None = Form(None),
                     text: str | None = Form(None), tenant: uuid.UUID = Depends(current_tenant)) -> dict:
        if file is not None:
            data = await file.read()
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "File larger than 10 MB")
            content, source = _read_upload(file, data), file.filename
        elif text:
            content, source = text, None
        else:
            raise HTTPException(422, "Send a file or a text field")

        chunks = chunk_text(content)
        if not chunks:
            raise HTTPException(422, "No text found in the document")
        doc_id = store.add_document(tenant, title or source or "Untitled", source, chunks, embedder.embed(chunks))
        return {"document_id": doc_id, "chunks": len(chunks)}

    @app.get("/documents")
    def documents(tenant: uuid.UUID = Depends(current_tenant)) -> list[dict]:
        return store.list_documents(tenant)

    @app.delete("/documents/{document_id}", status_code=204)
    def delete(document_id: uuid.UUID, tenant: uuid.UUID = Depends(current_tenant)) -> None:
        if not store.delete_document(tenant, document_id):
            raise HTTPException(404, "Document not found")  # same answer whether it's missing or another tenant's

    @app.post("/query", response_model=QueryOut)
    def query(body: QueryIn, tenant: uuid.UUID = Depends(current_tenant)) -> QueryOut:
        [q] = embedder.embed([body.question])
        hits = [h for h in store.search(tenant, q, body.top_k) if h["score"] >= MIN_SCORE]
        answer = generator.answer(body.question, [h["content"] for h in hits])
        return QueryOut(
            answer=answer,
            citations=[
                Citation(n=i, document_id=h["document_id"], title=h["title"], chunk_index=h["chunk_index"],
                         score=round(float(h["score"]), 4), excerpt=h["content"][:300])
                for i, h in enumerate(hits, 1)
            ],
        )

    return app


def app_from_env() -> FastAPI:
    """uvicorn rag_saas.api:app_from_env --factory"""
    from dotenv import load_dotenv

    from .providers import ExtractiveGenerator, HashingEmbedder, OpenAIEmbedder, OpenAIGenerator

    load_dotenv()
    dim = int(os.getenv("EMBED_DIM", "1536"))
    key = os.getenv("OPENAI_API_KEY")
    embedder = OpenAIEmbedder(key, dim=dim) if key else HashingEmbedder(dim)
    generator = OpenAIGenerator(key) if key else ExtractiveGenerator()
    return create_app(
        Store(os.environ["APP_DATABASE_URL"]), embedder, generator,
        admin_url=os.environ["ADMIN_DATABASE_URL"], admin_token=os.getenv("ADMIN_TOKEN", ""),
    )
