from tests.auth.conftest import csrf
from tests.knowledge.conftest import create_kb

DEFAULT_CONTENT = "校园图书馆周一开放。".encode()


def upload(client, kb, filename="guide.txt", content=DEFAULT_CONTENT):
    return client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": (filename, content)},
        headers=csrf(client),
    )


def test_upload_deduplicates_and_hides_storage(client, admin):
    kb = create_kb(client)
    first = upload(client, kb)
    assert first.status_code == 202, first.text
    again = upload(client, kb)
    assert again.json() == first.json()
    detail = client.get("/api/v1/documents/" + first.json()["document_id"]).json()
    assert detail["active_revision_id"] is None
    assert detail["candidate_revision"]["content_sha256"]
    assert "storage_key" not in str(detail)
    assert detail["latest_job"]["state"] == "queued"


def test_upload_type_size_and_path_validation(client, admin):
    kb = create_kb(client)
    for name in ["../evil.txt", "C:\\evil.txt", "/tmp/evil.txt", "bad.exe"]:
        assert upload(client, kb, name).status_code == 422
    assert upload(client, kb, content=b"x" * (20 * 1024 * 1024 + 1)).status_code == 413


def test_disable_delete_and_reenable(client, admin):
    kb = create_kb(client)
    document = upload(client, kb).json()["document_id"]
    url = "/api/v1/documents/" + document
    assert client.get(url + "/download").content.decode() == "校园图书馆周一开放。"
    assert (
        client.patch(url, json={"is_active": False}, headers=csrf(client)).json()["status"]
        == "disabled"
    )
    assert client.get(url + "/download").status_code == 404
    assert client.patch(url, json={"is_active": True}, headers=csrf(client)).status_code == 200
    assert client.delete(url, headers=csrf(client)).status_code == 204
    assert client.get(url).status_code == 404


def test_chunked_multipart_is_bounded_before_storage(client, admin, auth_app):
    kb = create_kb(client)
    boundary = "test-ingestion-boundary"

    def body():
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="large.txt"\r\n\r\n'
        ).encode()
        for _ in range(21):
            yield b"x" * (1024 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        content=body(),
        headers={**csrf(client), "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["request_id"]
    assert not list(auth_app.state.settings.upload_dir.iterdir())


def test_content_length_is_bounded_before_storage(client, admin, auth_app):
    kb = create_kb(client)
    response = upload(client, kb, content=b"x" * (21 * 1024 * 1024))
    assert response.status_code == 413
    assert not list(auth_app.state.settings.upload_dir.iterdir())
