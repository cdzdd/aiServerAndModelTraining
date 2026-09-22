from fastapi import Request
from fastapi.responses import JSONResponse


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict] | None = None,
) -> JSONResponse:
    error = {"code": code, "message": message, "request_id": request.state.request_id}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})
