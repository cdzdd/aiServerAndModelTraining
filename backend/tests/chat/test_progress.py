import asyncio

from app.modules.rag.schemas import AnswerEvent


def test_progress_is_visible_before_completion_without_exposing_partial_text():
    from app.modules.compute.progress import report_stage, stream_with_progress

    async def run():
        complete = asyncio.Event()

        async def source():
            report_stage("queued")
            await complete.wait()
            report_stage("validating")
            yield AnswerEvent(type="delta", payload={"text": "已验证的回答"})

        stream = stream_with_progress(source())
        first = await anext(stream)
        assert first.type == "progress"
        assert set(first.payload) == {"stage"}
        complete.set()
        rest = [event async for event in stream]
        assert any(event.type == "delta" for event in rest)

    asyncio.run(run())


def test_closing_progress_stream_cancels_the_underlying_request():
    from app.modules.compute.progress import report_stage, stream_with_progress

    async def run():
        started, closed = asyncio.Event(), asyncio.Event()

        async def source():
            try:
                started.set()
                report_stage("generating")
                await asyncio.Event().wait()
                yield AnswerEvent(type="delta", payload={"text": "不应出现"})
            finally:
                closed.set()

        stream = stream_with_progress(source())
        await anext(stream)
        await started.wait()
        await stream.aclose()
        assert closed.is_set()

    asyncio.run(run())


def test_parallel_requests_receive_only_their_own_progress():
    from app.modules.compute.progress import report_stage, stream_with_progress

    async def run():
        async def source(stage):
            report_stage(stage)
            await asyncio.sleep(0.01)
            yield AnswerEvent(type="delta", payload={"text": stage})

        async def collect(stage):
            return [event async for event in stream_with_progress(source(stage))]

        first, second = await asyncio.gather(collect("retrieving"), collect("generating"))
        assert {e.payload["stage"] for e in first if e.type == "progress"} <= {
            "preparing", "retrieving"
        }
        assert {e.payload["stage"] for e in second if e.type == "progress"} <= {
            "preparing", "generating"
        }

    asyncio.run(run())
