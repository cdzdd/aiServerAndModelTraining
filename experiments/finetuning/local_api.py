"""Private buffered OpenAI SSE bridge for the isolated LLaMAFactory experiment."""

import argparse
import asyncio
import json
import secrets
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field


class BusyGeneration(RuntimeError):
    pass


class GenerationGate:
    """Cancellation does not release a GPU worker that is still generating."""

    def __init__(self):
        self.busy = False

    async def run(self, operation):
        if self.busy:
            raise BusyGeneration("busy")
        self.busy = True
        task = asyncio.create_task(operation())

        def release(completed):
            self.busy = False
            if not completed.cancelled():
                completed.exception()  # Consume failures even when the HTTP caller disconnected.

        task.add_done_callback(release)
        return await asyncio.shield(task)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=8)
    stream: Literal[True]
    max_tokens: int = Field(strict=True, ge=1, le=512)
    temperature: float = Field(ge=0, le=0)


def require_local(request):
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "LOCAL_ACCESS_REQUIRED")


def create_app(chat_model, *, token, model_id):
    if len(token) < 32 or not token.isascii() or any(ord(char) < 33 for char in token):
        raise ValueError("a private ASCII credential of at least 32 characters is required")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    gate = GenerationGate()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"error": "INVALID_REQUEST"}, status_code=422)

    @app.get("/health")
    async def health(request: Request):
        require_local(request)
        return {"status": "ready", "model": model_id}

    @app.post("/v1/chat/completions")
    async def completion(request: Request, body: Completion):
        require_local(request)
        supplied = request.headers.get("Authorization", "")
        if not secrets.compare_digest(
            supplied.encode("utf-8"), ("Bearer " + token).encode("ascii")
        ):
            raise HTTPException(401, "PRIVATE_KEY_REQUIRED")
        if body.model != model_id:
            raise HTTPException(400, "MODEL_NOT_ALLOWED")
        messages = [message.model_dump() for message in body.messages]
        try:
            if any(not m["content"].strip() or "\x00" in m["content"] for m in messages):
                raise ValueError
            if sum(len(m["content"].encode()) for m in messages) > 12000:
                raise ValueError
        except (ValueError, UnicodeEncodeError):
            raise HTTPException(400, "INVALID_MESSAGES") from None
        system = None
        if messages[0]["role"] == "system":
            system = messages.pop(0)["content"]
        if (
            not messages
            or len(messages) % 2 != 1
            or any(
                message["role"] != ("user" if index % 2 == 0 else "assistant")
                for index, message in enumerate(messages)
            )
        ):
            raise HTTPException(400, "INVALID_ROLE_ORDER")

        async def generate():
            return await chat_model.achat(
                messages, system, max_new_tokens=body.max_tokens, do_sample=False
            )

        try:
            responses = await gate.run(generate)
            if len(responses) != 1:
                raise ValueError
            result = responses[0]
            if (
                result.finish_reason not in {"stop", "length"}
                or any(
                    type(count) is not int or count < 0
                    for count in (result.prompt_length, result.response_length)
                )
                or not isinstance(result.response_text, str)
            ):
                raise ValueError
            if len(result.response_text.encode()) > 60000 or "\x00" in result.response_text:
                raise ValueError
        except BusyGeneration:
            raise HTTPException(429, "GENERATION_BUSY") from None
        except Exception:  # noqa: BLE001 - never expose model errors or private prompt text
            raise HTTPException(503, "LOCAL_GENERATION_FAILED") from None

        def events():
            def event(choice, usage=None):
                data = {"model": model_id, "choices": [choice]}
                if usage is not None:
                    data["usage"] = usage
                return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"

            yield event(
                {"index": 0, "delta": {"content": result.response_text}, "finish_reason": None}
            )
            yield event(
                {"index": 0, "delta": {}, "finish_reason": result.finish_reason},
                {
                    "prompt_tokens": result.prompt_length,
                    "completion_tokens": result.response_length,
                    "total_tokens": result.prompt_length + result.response_length,
                },
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    return app


def enforce_greedy(chat_model):
    # Transformers 4.57 treats explicit False as a global default and may replace it
    # with the loaded model's True. Align that in-memory default before HF generate.
    chat_model.engine.model.generation_config.do_sample = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--model-id", default="qwen3-4b-qlora-demo")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    token = args.key_file.read_text(encoding="utf-8").strip()
    # Validate before loading weights; imports stay out of the business test environment.
    create_app(None, token=token, model_id=args.model_id)
    import uvicorn
    import yaml
    from llamafactory.chat import ChatModel

    config = yaml.safe_load(args.config.read_text(encoding="utf-8-sig"))
    model = ChatModel(config)
    enforce_greedy(model)
    uvicorn.run(
        create_app(model, token=token, model_id=args.model_id),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
