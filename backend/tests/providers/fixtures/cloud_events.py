import asyncio
import json
from contextlib import asynccontextmanager, suppress


def event(text=None, *, finish=None, usage=None, delta=None):
    payload = {
        "id": "fake-chat",
        "object": "chat.completion.chunk",
        "model": "fake-model",
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
    }
    if text is not None:
        payload["choices"][0]["delta"]["content"] = text
    if usage is not None:
        payload["choices"] = []
        payload["usage"] = usage
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\r\n\r\n").encode()


DONE = b"data: [DONE]\r\n\r\n"


@asynccontextmanager
async def cloud_server(
    parts=(), *, status=200, hold=False, delay_headers=0, content_type=None, content_encoding=None
):
    requests = []
    closed = asyncio.Event()
    tasks = set()
    writers = set()

    async def handle(reader, writer):
        tasks.add(asyncio.current_task())
        writers.add(writer)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode().split("\r\n")
            headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
            body = await reader.readexactly(int(headers.get("Content-Length", 0)))
            requests.append((lines[0], headers, json.loads(body)))
            await asyncio.sleep(delay_headers)
            media = content_type or "text/event-stream"
            encoding = f"Content-Encoding: {content_encoding}\r\n" if content_encoding else ""
            writer.write(
                (
                    f"HTTP/1.1 {status} Test\r\nContent-Type: {media}\r\n"
                    + encoding
                    + "Transfer-Encoding: chunked\r\n\r\n"
                ).encode()
            )
            await writer.drain()
            for part in parts:
                writer.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                await writer.drain()
                await asyncio.sleep(0.001)
            if hold:
                await reader.read()
            else:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            closed.set()
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            writers.discard(writer)
            tasks.discard(asyncio.current_task())

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/v1", requests, closed
    finally:
        server.close()
        for writer in list(writers):
            writer.close()
        remaining = list(tasks)
        for task in remaining:
            task.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)
        await server.wait_closed()
