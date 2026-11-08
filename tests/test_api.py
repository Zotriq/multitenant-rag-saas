from rag_saas.chunking import chunk_text
from tests.conftest import h


def test_admin_creates_tenant_and_key_works_once_shown(client):
    assert client.post("/admin/tenants", json={"name": "New Co"}).status_code == 403
    res = client.post("/admin/tenants", json={"name": "New Co"}, headers={"X-Admin-Token": "admin-secret"})
    assert res.status_code == 201
    key = res.json()["api_key"]
    assert key.startswith("rag_")
    assert client.get("/documents", headers=h(key)).status_code == 200


def test_file_upload_and_validation(client, tenants):
    key = tenants["Acme Law"][1]
    res = client.post("/documents", headers=h(key), files={"file": ("faq.md", b"# FAQ\n\nWe are open on Saturdays.", "text/markdown")})
    assert res.status_code == 201 and res.json()["chunks"] == 1
    assert client.post("/documents", headers=h(key), files={"file": ("a.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post("/documents", headers=h(key), data={"text": "   "}).status_code == 422


def test_question_with_no_relevant_documents(client, tenants):
    key = tenants["Globex Clinic"][1]
    res = client.post("/query", headers=h(key), json={"question": "What is the refund policy?"}).json()
    assert res["citations"] == [] and res["answer"].startswith("I don't know")


def test_chunking_respects_size_and_overlap():
    text = ("Sentence number %d is here. " * 200) % tuple(range(200))
    chunks = chunk_text(text, max_chars=500, overlap=80)
    assert len(chunks) > 5 and all(len(c) <= 500 for c in chunks)
    assert chunks[0][-40:].split()[-1] in chunks[1]  # overlap carries context forward
    assert chunk_text("") == []
