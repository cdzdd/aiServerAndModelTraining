from chat_stream_helpers import sign_in
from chat_stream_helpers import stream_app as stream_app
from chat_stream_helpers import stream_client as stream_client

from app.modules.providers.queued import QueuedProvider


def test_progress_is_negotiated_and_does_not_change_legacy_clients(stream_app, stream_client):
    from uuid import uuid4

    from chat_stream_helpers import conversation, parse_sse

    _, headers = sign_in(stream_client)
    cid = conversation(stream_client, stream_app, headers)
    path = f"/api/v1/conversations/{cid}/messages/stream"
    response = stream_client.post(
        path + "?progress=true",
        headers=headers,
        json={"content": "图书馆几点开门？", "client_message_id": str(uuid4())},
    )
    events = parse_sse(response.text)
    assert events[0][0] == "meta"
    progress = [payload for kind, payload in events if kind == "progress"]
    assert progress == [{"stage": "preparing"}]
    assert [kind for kind, _ in events if kind != "progress"] == [
        "meta", "delta", "citations", "done"
    ]


def test_model_status_requires_login(stream_client):
    assert stream_client.get("/api/v1/model/status").status_code == 401


def test_offline_model_status_does_not_expose_node_metadata(stream_app, stream_client):
    sign_in(stream_client)
    stream_app.state.chat_rag.provider = QueuedProvider(
        stream_app.state.session_factory, model_id="model-fixture", max_output_tokens=512
    )
    response = stream_client.get("/api/v1/model/status")
    assert response.status_code == 200
    assert response.json() == {
        "state": "offline",
        "available": False,
        "provider": "queued",
        "model_id": "model-fixture",
    }
    assert response.headers["cache-control"] == "no-store"


def test_nonqueued_status_reports_configuration_without_probe(stream_app, stream_client):
    from app.modules.providers.mock import MockProvider

    sign_in(stream_client)
    stream_app.state.chat_rag.provider = MockProvider()
    response = stream_client.get("/api/v1/model/status")
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    assert response.json()["state"] == "ready"
