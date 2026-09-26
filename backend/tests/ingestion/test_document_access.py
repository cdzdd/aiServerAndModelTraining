from tests.auth.conftest import csrf
from tests.ingestion.test_uploads import upload
from tests.knowledge.conftest import create_kb, members


def test_download_and_detail_check_current_membership(client, admin, reader):
    other, person = reader
    kb = create_kb(client)
    document = upload(client, kb).json()["document_id"]
    url = "/api/v1/documents/" + document
    for suffix in ["", "/download"]:
        assert other.get(url + suffix).status_code == 404
    granted = members(client, kb, [person["id"]]).json()
    assert other.get(url + "/download").status_code == 200
    assert other.post(url + "/reindex", headers=csrf(other)).status_code == 403
    members(client, {**kb, "version": granted["version"]}, [])
    assert other.get(url + "/download").status_code == 404
    assert other.get(url).status_code == 404
