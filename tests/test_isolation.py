"""The point of this project: one tenant can never see or touch another tenant's data."""

import psycopg

from tests.conftest import h

ACME_DOC = "Acme Law retainer policy. Our hourly rate for litigation is 450 dollars. Retainers are refundable within 30 days."
GLOBEX_DOC = "Globex Clinic opening hours. The clinic opens at 8am and closes at 6pm. Walk-in patients are seen until 5pm."


def upload(client, key, text, title):
    res = client.post("/documents", headers=h(key), data={"text": text, "title": title})
    assert res.status_code == 201, res.text
    return res.json()["document_id"]


def test_each_tenant_only_sees_its_own_documents(client, tenants):
    acme, globex = tenants["Acme Law"][1], tenants["Globex Clinic"][1]
    upload(client, acme, ACME_DOC, "Retainer policy")
    upload(client, globex, GLOBEX_DOC, "Opening hours")

    assert [d["title"] for d in client.get("/documents", headers=h(acme)).json()] == ["Retainer policy"]
    assert [d["title"] for d in client.get("/documents", headers=h(globex)).json()] == ["Opening hours"]


def test_search_never_returns_another_tenants_chunks(client, tenants):
    acme, globex = tenants["Acme Law"][1], tenants["Globex Clinic"][1]
    upload(client, acme, ACME_DOC, "Retainer policy")
    upload(client, globex, GLOBEX_DOC, "Opening hours")

    # Globex asks a question that only Acme's document answers.
    res = client.post("/query", headers=h(globex), json={"question": "What is the hourly rate for litigation?"}).json()
    assert all(c["title"] == "Opening hours" for c in res["citations"])
    assert "450" not in res["answer"]

    res = client.post("/query", headers=h(acme), json={"question": "What is the hourly rate for litigation?"}).json()
    assert res["citations"][0]["title"] == "Retainer policy"
    assert "450 dollars" in res["answer"] and res["answer"].endswith("[1]")


def test_cannot_delete_another_tenants_document_even_with_its_id(client, tenants):
    acme, globex = tenants["Acme Law"][1], tenants["Globex Clinic"][1]
    doc_id = upload(client, acme, ACME_DOC, "Retainer policy")
    assert client.delete(f"/documents/{doc_id}", headers=h(globex)).status_code == 404
    assert len(client.get("/documents", headers=h(acme)).json()) == 1
    assert client.delete(f"/documents/{doc_id}", headers=h(acme)).status_code == 204
    assert client.get("/documents", headers=h(acme)).json() == []


def test_database_enforces_isolation_without_any_app_code(db, tenants):
    """Connect as the app role directly. A query with no WHERE clause still only sees the current tenant."""
    acme_id, globex_id = tenants["Acme Law"][0], tenants["Globex Clinic"][0]
    with psycopg.connect(db["app"]) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(acme_id),))
        conn.execute("INSERT INTO documents (title) VALUES ('acme only')")
        conn.commit()

        # No tenant set at all: nothing is visible.
        conn.execute("RESET app.tenant_id")
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0

        # Another tenant: still invisible, and it can't write rows claiming to be Acme.
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(globex_id),))
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
        try:
            conn.execute("INSERT INTO documents (tenant_id, title) VALUES (%s, 'spoofed')", (acme_id,))
            raise AssertionError("insert into another tenant should have failed")
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()


def test_app_role_cannot_bypass_rls(db):
    with psycopg.connect(db["admin"]) as conn:
        row = conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'rag_app'").fetchone()
    assert row == (False, False)


def test_auth(client, tenants):
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers=h("rag_wrong")).status_code == 401
