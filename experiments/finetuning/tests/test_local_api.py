import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from experiments.finetuning.local_api import create_app
from fastapi.testclient import TestClient


class Generator:
    def __init__(self, reason="stop", fail=False):
        self.reason = reason
        self.fail = fail
        self.inputs = []

    async def achat(self, messages, system, **kwargs):
        self.inputs.append((messages, system, kwargs))
        if self.fail:
            raise RuntimeError("secret credential and private source content")
        return [
            SimpleNamespace(
                response_text='{"status":"no_answer","selections":[]}',
                response_length=14,
                prompt_length=103,
                finish_reason=self.reason,
            )
        ]


def client(generator=None):
    return TestClient(
        create_app(generator or Generator(), token="a" * 32, model_id="teaching-qwen"),
        client=("127.0.0.1", 50000),
    )


def payload():
    return {
        "model": "teaching-qwen",
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "question"},
        ],
        "stream": True,
        "max_tokens": 128,
        "temperature": 0,
    }


@pytest.mark.parametrize("reason", ["stop", "length"])
def test_buffered_sse_preserves_real_finish_reason_and_token_counts(reason):
    generator = Generator(reason)
    response = client(generator).post(
        "/v1/chat/completions", json=payload(), headers={"Authorization": "Bearer " + "a" * 32}
    )
    assert response.status_code == 200
    events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    final = json.loads(events[-2])
    assert final["choices"][0]["finish_reason"] == reason
    assert final["usage"] == {"prompt_tokens": 103, "completion_tokens": 14, "total_tokens": 117}
    assert generator.inputs == [
        (
            [{"role": "user", "content": "question"}],
            "rules",
            {"max_new_tokens": 128, "do_sample": False},
        )
    ]


def test_private_key_fixed_model_and_loopback_are_enforced():
    generator = Generator()
    app = create_app(generator, token="a" * 32, model_id="teaching-qwen")
    local = TestClient(app, client=("127.0.0.1", 50000))
    assert local.post("/v1/chat/completions", json=payload()).status_code == 401
    wrong_model = dict(payload(), model="other")
    assert (
        local.post(
            "/v1/chat/completions",
            json=wrong_model,
            headers={"Authorization": "Bearer " + "a" * 32},
        ).status_code
        == 400
    )
    external = TestClient(app, client=("192.0.2.1", 50000))
    assert (
        external.post(
            "/v1/chat/completions", json=payload(), headers={"Authorization": "Bearer " + "a" * 32}
        ).status_code
        == 403
    )
    assert generator.inputs == []


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(max_tokens=513),
        lambda p: p.update(temperature=0.1),
        lambda p: p.update(messages=[{"role": "assistant", "content": "question"}]),
        lambda p: p.update(messages=[{"role": "user", "content": "x" * 12001}]),
        lambda p: p.update(tools=[{}]),
    ],
)
def test_unsupported_or_oversized_requests_never_generate(change):
    body = payload()
    change(body)
    generator = Generator()
    response = client(generator).post(
        "/v1/chat/completions", json=body, headers={"Authorization": "Bearer " + "a" * 32}
    )
    assert response.status_code in {400, 422}
    assert generator.inputs == []


def test_upstream_failure_is_safe_and_has_no_success_done():
    response = client(Generator(fail=True)).post(
        "/v1/chat/completions", json=payload(), headers={"Authorization": "Bearer " + "a" * 32}
    )
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "[DONE]" not in response.text


def test_generation_remains_busy_after_client_cancellation_until_worker_finishes():
    from experiments.finetuning.local_api import GenerationGate

    async def scenario():
        finished = asyncio.Event()
        gate = GenerationGate()

        async def operation():
            await finished.wait()
            return ["result"]

        task = asyncio.create_task(gate.run(operation))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.busy
        with pytest.raises(RuntimeError, match="busy"):
            await gate.run(operation)
        finished.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not gate.busy

    asyncio.run(scenario())


def test_nonascii_authorization_is_rejected_without_server_error():
    response = client().post(
        "/v1/chat/completions", json=payload(), headers={b"Authorization": b"Bearer \xff"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("reason", ["stop", "length"])
def test_business_provider_consumes_actual_loopback_sse_without_relabeling(reason):
    import socket
    import threading
    import time

    import uvicorn
    from pydantic import SecretStr

    from app.modules.providers.cloud import CloudProvider
    from app.modules.providers.config import ModelSettings
    from app.modules.providers.schemas import LLMMessage

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Generator(reason), token="a" * 32, model_id="teaching-qwen"),
            log_level="critical",
            access_log=False,
            lifespan="off",
            proxy_headers=False,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        settings = ModelSettings(
            _env_file=None,
            model_provider="cloud",
            model_base_url=f"http://127.0.0.1:{port}/v1",
            model_id="teaching-qwen",
            model_allowed_ids=["teaching-qwen"],
            model_api_key=SecretStr("a" * 32),
        )

        async def request():
            return [
                part
                async for part in CloudProvider(settings).stream(
                    [
                        LLMMessage(role="system", content="rules"),
                        LLMMessage(role="user", content="question"),
                    ],
                    max_tokens=128,
                    temperature=0,
                )
            ]

        parts = asyncio.run(request())
        assert parts[-1].finish_reason == reason
        assert parts[-1].usage.prompt_tokens == 103
        assert parts[-1].usage.completion_tokens == 14
        assert parts[-1].usage.total_tokens == 117
        assert "no_answer" in "".join(part.text for part in parts)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_main_serves_requested_full_bf16_parameters(monkeypatch, tmp_path):
    import torch
    from experiments.finetuning import local_api

    model = torch.nn.Linear(2, 2).eval().requires_grad_(False)
    model.generation_config = SimpleNamespace(do_sample=True)
    chat = SimpleNamespace(engine=SimpleNamespace(model=model))
    config = tmp_path / "inference.yaml"
    config.write_text("finetuning_type: full\ninfer_dtype: bfloat16\n", encoding="utf-8")
    key = tmp_path / "private-key"
    key.write_text("a" * 32, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["local_api", "--config", str(config), "--key-file", str(key)])

    def native_chat(parsed):
        assert parsed == {"finetuning_type": "full", "infer_dtype": "bfloat16"}
        assert all(parameter.dtype == torch.float32 for parameter in model.parameters())
        return chat

    served = []

    def serve(app, **kwargs):
        assert all(parameter.dtype == torch.bfloat16 for parameter in model.parameters())
        assert model.generation_config.do_sample is False
        served.append(app)

    monkeypatch.setitem(sys.modules, "llamafactory.chat", SimpleNamespace(ChatModel=native_chat))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=serve))
    local_api.main()
    assert len(served) == 1


def inference_module(dtype=None):
    import torch

    model = torch.nn.Module()
    model.weight = torch.nn.Parameter(torch.tensor([0.1, -0.7], dtype=dtype or torch.float32))
    model.tied_weight = model.weight
    model.frozen = torch.nn.Parameter(torch.tensor([0.3], dtype=dtype or torch.float32), False)
    model.register_buffer("inv_freq", torch.tensor([1.0, 0.01], dtype=torch.float32))
    model.config = SimpleNamespace(dtype="float32", use_cache=True)
    model.generation_config = SimpleNamespace(do_sample=True, num_beams=1)
    model._hf_peft_config_loaded = False  # Native HF's unused adapter mixin is not PEFT state.
    return model


def parameter_identity(model):
    return {
        name: (id(parameter), parameter.data_ptr(), parameter.dtype, parameter.requires_grad)
        for name, parameter in model.named_parameters(remove_duplicate=False)
    }


def test_full_bf16_cast_preserves_parameter_aliases_buffers_and_configs():
    import torch
    from experiments.finetuning.local_api import enforce_full_bf16

    model = inference_module()
    before = parameter_identity(model)
    native_casts = {name: p.detach().to(torch.bfloat16) for name, p in model.named_parameters()}
    buffer = model.inv_freq
    buffer_bytes = buffer.view(torch.uint8).clone()
    config = model.config
    generation = model.generation_config
    config_values = vars(config).copy()
    generation_values = vars(generation).copy()
    enforce_full_bf16(
        SimpleNamespace(engine=SimpleNamespace(model=model)),
        {"finetuning_type": "full", "infer_dtype": "bfloat16"},
    )
    for name, parameter in model.named_parameters(remove_duplicate=False):
        assert parameter.dtype == torch.bfloat16
        assert id(parameter) == before[name][0]
        assert parameter.requires_grad == before[name][3]
        assert parameter.device.type == "cpu"
    for name, parameter in model.named_parameters():
        assert torch.equal(parameter, native_casts[name])
    assert model.weight is model.tied_weight
    assert model.inv_freq is buffer
    assert model.inv_freq.dtype == torch.float32
    assert torch.equal(model.inv_freq.view(torch.uint8), buffer_bytes)
    assert model.config is config and vars(config) == config_values
    assert model.generation_config is generation and vars(generation) == generation_values


def test_already_bf16_full_model_and_repeat_call_leave_storage_untouched():
    import torch
    from experiments.finetuning.local_api import enforce_full_bf16

    model = inference_module(torch.bfloat16)
    before = parameter_identity(model)
    values = {name: p.detach().clone() for name, p in model.named_parameters()}
    chat = SimpleNamespace(engine=SimpleNamespace(model=model))
    config = {"finetuning_type": "full", "infer_dtype": "bfloat16"}
    enforce_full_bf16(chat, config)
    enforce_full_bf16(chat, config)
    assert parameter_identity(model) == before
    assert all(torch.equal(parameter, values[name]) for name, parameter in model.named_parameters())


@pytest.mark.parametrize(
    "config",
    [
        {"finetuning_type": "lora", "infer_dtype": "bfloat16"},
        {"finetuning_type": "freeze", "infer_dtype": "bfloat16"},
        {"finetuning_type": "full", "infer_dtype": "auto"},
        {"finetuning_type": "full", "infer_dtype": "float16"},
        {},
    ],
)
def test_other_inference_modes_retain_their_existing_parameters(config):
    from experiments.finetuning.local_api import enforce_full_bf16

    model = inference_module()
    model.peft_config = {"default": object()}
    model.is_loaded_in_4bit = True
    before = parameter_identity(model)
    enforce_full_bf16(SimpleNamespace(engine=SimpleNamespace(model=model)), config)
    assert parameter_identity(model) == before


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("is_quantized", True),
        ("is_loaded_in_4bit", True),
        ("is_loaded_in_8bit", True),
        ("hf_quantizer", object()),
        ("peft_config", {"default": object()}),
        ("_hf_peft_config_loaded", True),
    ],
)
def test_quantized_or_peft_full_model_is_rejected_before_any_cast(attribute, value):
    from experiments.finetuning.local_api import enforce_full_bf16

    model = inference_module()
    setattr(model, attribute, value)
    before = parameter_identity(model)
    with pytest.raises(ValueError, match="FULL_BF16.*QUANT_OR_ADAPTER"):
        enforce_full_bf16(
            SimpleNamespace(engine=SimpleNamespace(model=model)),
            {"finetuning_type": "full", "infer_dtype": "bfloat16"},
        )
    assert parameter_identity(model) == before


@pytest.mark.parametrize("dtype_name", ["float16", "float64", "int64"])
def test_unsupported_full_parameter_dtype_rejects_without_partial_mutation(dtype_name):
    import torch
    from experiments.finetuning.local_api import enforce_full_bf16

    model = inference_module()
    model.frozen.data = model.frozen.data.to(getattr(torch, dtype_name))
    before = parameter_identity(model)
    with pytest.raises(ValueError, match="FULL_BF16.*PARAMETER_DTYPE"):
        enforce_full_bf16(
            SimpleNamespace(engine=SimpleNamespace(model=model)),
            {"finetuning_type": "full", "infer_dtype": "bfloat16"},
        )
    assert parameter_identity(model) == before
