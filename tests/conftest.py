import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from rag_saas.api import create_app
from rag_saas.db import Store, create_tenant, migrate
from rag_saas.providers import ExtractiveGenerator, HashingEmbedder

ADMIN_URL = os.getenv("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="set PG_ADMIN_URL (a pgvector-enabled database)")
DIM = 64


def app_url(admin_url: str) -> str:
    """Same database, but connecting as the low-privilege rag_app role."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(admin_url)
    info.update(user="rag_app", password="rag_app")
    return make_conninfo(**info)


@pytest.fixture(scope="session")
def db():
    if not ADMIN_URL:
        pytest.skip("set PG_ADMIN_URL")
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS chunks, documents, api_keys, tenants CASCADE")
    migrate(ADMIN_URL, DIM)
    return {"admin": ADMIN_URL, "app": app_url(ADMIN_URL)}


@pytest.fixture
def tenants(db):
    return {name: create_tenant(db["admin"], name) for name in ("Acme Law", "Globex Clinic")}


@pytest.fixture
def client(db):
    app = create_app(Store(db["app"]), HashingEmbedder(DIM), ExtractiveGenerator(), admin_url=db["admin"], admin_token="admin-secret")
    return TestClient(app)


def h(api_key):
    return {"X-API-Key": api_key}
