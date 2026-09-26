"""Small allowlisted JSON records; never accept exception text or request payloads."""

import json
import logging
import sys
from contextvars import ContextVar
from http import HTTPStatus
from uuid import UUID

request_id_context = ContextVar("request_id", default=None)
_CURRENT = object()
_CODES = {status.name for status in HTTPStatus} | set(
    """
UNKNOWN_ERROR INTERNAL_ERROR VALIDATION_ERROR DEPENDENCY_UNAVAILABLE
UNAUTHENTICATED INVALID_CREDENTIALS CSRF_FAILED IDENTITY_CHANGED RATE_LIMITED
ALREADY_INITIALIZED FILE_TOO_LARGE UNSUPPORTED_TYPE INVALID_FILENAME
INVALID_INPUT INVALID_OUTPUT INVALID_QUERY INVALID_TOP_K CONTEXT_LIMIT
CHAT_RATE_LIMITED CHAT_UNAVAILABLE
DUPLICATE_MESSAGE CONVERSATION_STATE GENERATION_IN_PROGRESS HANDOFF_STATE_CONFLICT
FEEDBACK_UNAVAILABLE FEEDBACK_EXISTS PROVIDER_CONFIG_ERROR PROVIDER_BAD_REQUEST
PROVIDER_AUTH_FAILED PROVIDER_RATE_LIMITED PROVIDER_UNAVAILABLE PROVIDER_TIMEOUT
PROVIDER_STREAM_INTERRUPTED PROVIDER_PROTOCOL_ERROR PROVIDER_EMPTY_RESPONSE
PROVIDER_UNSUPPORTED_RESPONSE QUESTION_INVALID HISTORY_INVALID RAG_TIMEOUT
RAG_INVALID_OUTPUT SOURCE_CHANGED MODEL_INDEX_MISMATCH MODEL_UNAVAILABLE
MODEL_INTEGRITY ENCODE_FAILED RAG_UNAVAILABLE INVALID_CITATION NO_TEXT INVALID_FORMAT
PARSE_LIMIT PARSE_TIMEOUT TOKENIZER_UNAVAILABLE PARSE_FAILED SUPERSEDED TOKEN_LIMIT
CHAT_FINALIZATION_FAILED CHAT_CANCELLATION_PERSISTENCE_FAILED CHAT_STREAM_CLOSE_FAILED
CHAT_RECOVERY_FAILED PROCESS_RESTARTED AUTHORITY_CHANGED CANCELLED INCOMPLETE_STREAM
GENERATION_FAILED GENERATION_REVOKED
""".split()
)
_EVENTS = {
    "rag_failure",
    "rag_refusal",
    "chat_finalization_failed",
    "chat_cancellation_persistence_failed",
    "chat_stream_close_failed",
    "chat_recovery_failed",
    "ingestion_job_failed",
}


class _SafeStreamHandler(logging.StreamHandler):
    def handleError(self, record):
        # logging's default fallback prints a traceback from the surrounding failure.
        pass


def configure_logging():
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = _SafeStreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def safe_error_code(code):
    return code if isinstance(code, str) and code in _CODES else "UNKNOWN_ERROR"


def _uuid(value):
    try:
        return str(UUID(str(value))) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def _emit(logger, level, payload):
    try:
        logger.log(level, json.dumps(payload, ensure_ascii=True))
    except Exception:
        # A broken output handler must not turn a committed business action into failure.
        pass


def log_failure(
    logger,
    event,
    code,
    *,
    request_id=_CURRENT,
    operation_id=None,
    job_id=None,
    kind=None,
    attempt=None,
    prompt_version=None,
):
    payload = {
        "event": event if event in _EVENTS else "application_failure",
        "error_code": safe_error_code(code),
        "request_id": _uuid(request_id_context.get() if request_id is _CURRENT else request_id),
    }
    if operation_id is not None:
        payload["operation_id"] = _uuid(operation_id)
    if job_id is not None:
        payload.update(
            job_id=_uuid(job_id),
            kind=kind if kind in {"parse", "index"} else None,
            attempt=attempt if type(attempt) is int and attempt >= 0 else None,
        )
    if prompt_version is not None:
        # The sole current producer has a fixed version, never model-returned text.
        payload["prompt_version"] = (
            prompt_version if prompt_version == "rag-extractive-v1" else None
        )
    _emit(logger, logging.ERROR if event.startswith("chat_") else logging.WARNING, payload)


def log_http(logger, *, request_id, method, route, status_code, error_code=None):
    _emit(
        logger,
        logging.INFO,
        {
            "event": "http_request",
            "request_id": _uuid(request_id),
            "method": method
            if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
            else "OTHER",
            "route": route,
            "status_code": status_code,
            "error_code": safe_error_code(error_code) if error_code is not None else None,
        },
    )
