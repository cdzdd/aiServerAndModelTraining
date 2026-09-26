"""Bound multipart bytes before Starlette spools uploaded files to disk."""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException

from app.core.errors import error_response
from app.modules.ingestion.storage import MAX_UPLOAD_BYTES


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if not headers.get("content-type", "").strip().lower().startswith("multipart/form-data"):
            return await self.app(scope, receive, send)
        limit = MAX_UPLOAD_BYTES + 64 * 1024
        raw_length = headers.get("content-length", "0")
        if raw_length.isdigit() and int(raw_length) > limit:
            from starlette.requests import Request

            request = Request(scope)
            response = error_response(request, 413, "FILE_TOO_LARGE", "文件不能超过 20 MiB")
            return await response(scope, receive, send)
        count = 0

        async def limited_receive():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > limit:
                raise HTTPException(413)
            return message

        return await self.app(scope, limited_receive, send)
