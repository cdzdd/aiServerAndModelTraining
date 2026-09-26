from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.request_context import safe_error_code


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict] | None = None,
) -> JSONResponse:
    request.state.error_code = safe_error_code(code)
    error = {"code": code, "message": message, "request_id": request.state.request_id}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})
