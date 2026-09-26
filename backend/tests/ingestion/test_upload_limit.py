import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.modules.ingestion.upload_limit import UploadLimitMiddleware


def test_duplicate_content_type_cannot_bypass_pre_spool_limit():
    boundary = "limit-test"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.txt"\r\n\r\n'
    ).encode() + b"x" * (21 * 1024 * 1024)
    body += f"\r\n--{boundary}--\r\n".encode()
    entered_parser = []
    messages = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/knowledge-bases/kb/documents",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-type", b"application/octet-stream"),
            (b"content-length", str(len(body)).encode()),
        ],
        "state": {"request_id": "duplicate-content-type-test"},
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    async def endpoint(scope, receive, send):
        entered_parser.append(True)
        async with Request(scope, receive).form() as form:
            response = JSONResponse({"size": form["file"].size})
        await response(scope, receive, send)

    asyncio.run(UploadLimitMiddleware(endpoint)(scope, receive, send))
    assert messages[0]["status"] == 413
    assert not entered_parser
