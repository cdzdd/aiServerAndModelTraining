"""Buffer at most 64 KiB before a machine route may mutate the database."""

from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request

from app.core.errors import error_response
from app.modules.compute.schemas import MAX_BODY_BYTES


def is_compute_path(path):
    return path == "/internal/compute" or path.startswith("/internal/compute/")


class ComputeBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not is_compute_path(scope["path"]):
            return await self.app(scope, receive, send)

        async def no_store(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        async def too_large():
            request = Request(scope)
            if not getattr(request.state, "request_id", None):
                request.state.request_id = str(uuid4())
            response = error_response(request, 413, "COMPUTE_BODY_TOO_LARGE", "计算请求过大")
            await response(scope, receive, no_store)

        length = Headers(scope=scope).get("content-length", "")
        if length.isdigit() and (len(length) > 6 or int(length) > MAX_BODY_BYTES):
            return await too_large()
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return await too_large()
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, buffered_receive, no_store)
