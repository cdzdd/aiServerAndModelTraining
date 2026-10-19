"""Full-training evidence must come from real parameters and actual optimizer updates."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
import yaml
from experiments.finetuning import run_training as training
from experiments.finetuning.prepare_data import prepare
from experiments.finetuning.run_training import factory_training_arguments, validate_recipe
from test_corpus import corpus_fixture
from torch import nn

ROOT = Path(__file__).resolve().parents[3]


def audit_module():
    try:
        return importlib.import_module("experiments.finetuning.audit_full_model")
    except ModuleNotFoundError:
        pytest.fail("missing full parameter audit module")


def full_recipe():
    path = ROOT / "experiments/finetuning/configs/full-0.6b.yaml"
    assert path.is_file(), "missing full-training recipe"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_full_requires_all_unique_params_trainable():
    model = nn.Linear(3, 2)
    model.bias.requires_grad_(False)
    with pytest.raises(ValueError, match="frozen"):
        audit_module().audit_full_model(model, torch.optim.AdamW(model.parameters()))


@pytest.mark.parametrize("foreign", [False, True])
def test_optimizer_covers_exact_model_params(foreign):
    model = nn.Linear(3, 2)
    params = list(model.parameters())
    if foreign:
        params.append(nn.Parameter(torch.ones(1)))
    else:
        params.pop()
    with pytest.raises(ValueError, match="optimizer.*parameters"):
        audit_module().audit_full_model(model, torch.optim.AdamW(params))


def test_tied_params_count_once():
    model = nn.Module()
    model.embedding = nn.Embedding(5, 3)
    model.head = nn.Linear(3, 5, bias=False)
    model.head.weight = model.embedding.weight
    result = audit_module().audit_full_model(model, torch.optim.AdamW(model.parameters()))
    assert result["total_parameters"] == result["trainable_parameters"] == 15
    assert result["optimizer_parameters"] == 15
    assert result["parameter_tensors"] == result["optimizer_parameter_tensors"] == 1
    assert result["parameter_dtypes"] == {"torch.float32": 15}
    assert result["layers"]["embedding"]["parameters"] == 15
    assert result["optimizer_state"]["tensor_count"] == 0


@pytest.mark.parametrize("kind", ["lora", "4bit", "quantized"])
def test_reject_lora_and_quantized_modules(kind):
    model = nn.Linear(3, 2)
    if kind == "lora":
        model.lora_A = nn.Linear(3, 1, bias=False)
    elif kind == "4bit":
        model.is_loaded_in_4bit = True
    else:
        model.is_quantized = True
    with pytest.raises(ValueError, match="adapter|quantiz"):
        audit_module().audit_full_model(model, torch.optim.AdamW(model.parameters()))


def test_reject_native_quantized_child_without_quantization_flag():
    model = nn.Sequential(nn.Linear(3, 3), torch.ao.nn.quantized.Linear(3, 2))
    with pytest.raises(ValueError, match="quantiz"):
        audit_module().audit_full_model(model, torch.optim.AdamW(model.parameters()))


def test_full_recipe_has_no_adapter_or_quantization(tmp_path):
    recipe = full_recipe()
    validate_recipe(recipe)
    manifest = tmp_path / "source.json"
    manifest.write_text(json.dumps(corpus_fixture()), encoding="utf-8")
    summary = prepare(
        tmp_path / "projection",
        model_path="/models/qwen-0.6b",
        runtime_root="/runs/full",
        manifest_path=manifest,
        recipe_path=ROOT / "experiments/finetuning/configs/full-0.6b.yaml",
    )
    configs = tmp_path / "projection/configs"
    train = yaml.safe_load((configs / "full-train.yaml").read_text())
    infer = yaml.safe_load((configs / "inference-finetuned.yaml").read_text())
    assert train["finetuning_type"] == infer["finetuning_type"] == "full"
    assert train["model_name_or_path"] == "/models/qwen-0.6b"
    assert infer["model_name_or_path"] == "/runs/full/train"
    assert infer["do_sample"] is False
    assert not any("lora" in key or "adapter" in key or "quant" in key for key in train)
    assert not any("lora" in key or "adapter" in key or "quant" in key for key in infer)
    assert not (configs / "qlora-train.yaml").exists()
    assert summary["input_manifest_sha256"] != summary["files_sha256"]["manifest-v2.json"]
    assert summary["token_audit"]["status"] == "pending_actual_frozen_tokenizer"


@pytest.mark.parametrize(
    "changes",
    [
        {"quantization_bit": 4},
        {"lora_rank": 16},
        {"freeze_trainable_layers": 2},
        {"adapter_name_or_path": None},
        {"pure_bf16": True},
        {"optim": "adamw_bnb_8bit"},
        {"model_revision": "main"},
        {"model_revision": "a" * 40},
        {"eval_steps": 50},
        {"restore_callback_states_from_checkpoint": False},
    ],
)
def test_full_recipe_rejects_nonfull_or_unpinned_training(changes):
    with pytest.raises(ValueError):
        validate_recipe({**full_recipe(), **changes})


@pytest.mark.parametrize("source,target", [(1020, 5), (1025, 1)])
def test_target_or_evidence_truncation_is_rejected(source, target):
    sample = {"id": "music-q:answer", "split": "train"}
    with pytest.raises(ValueError, match="truncation.*music-q:answer"):
        audit_module().audit_full_token_lengths(
            [sample], {sample["id"]: {"source_tokens": source, "target_tokens": target}}, 1024
        )


def test_token_lengths_require_exact_inventory_and_nonempty_target():
    sample = {"id": "music-q:answer", "split": "train"}
    function = audit_module().audit_full_token_lengths
    for lengths in ({}, {sample["id"]: {"source_tokens": 5, "target_tokens": 0}}):
        with pytest.raises(ValueError):
            function([sample], lengths, 1024)
    assert function([sample], {sample["id"]: {"source_tokens": 5, "target_tokens": 3}}, 1024)[
        "counts"
    ]["train"] == {"samples": 1, "max_source": 5, "max_target": 3, "max_total": 8}


class TinyQwen(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = nn.Module()
        self.model.embed_tokens = nn.Embedding(5, 3)
        layer = nn.Module()
        layer.self_attn = nn.Module()
        layer.self_attn.q_proj = nn.Linear(3, 3, bias=False)
        layer.mlp = nn.Module()
        layer.mlp.down_proj = nn.Linear(3, 3, bias=False)
        layer.input_layernorm = nn.LayerNorm(3)
        self.model.layers = nn.ModuleList([layer])

    def forward(self):
        layer = self.model.layers[0]
        values = self.model.embed_tokens(torch.tensor([0, 1]))
        return layer.mlp.down_proj(layer.self_attn.q_proj(layer.input_layernorm(values)))


def test_callback_records_real_update_and_preserves_initial_on_resume(tmp_path):
    from transformers import TrainerControl, TrainerState

    module = audit_module()
    model = TinyQwen()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    args = SimpleNamespace(output_dir=str(tmp_path))
    state, control = TrainerState(), TrainerControl()
    callback = module.FullModelAuditCallback()
    callback.on_train_begin(args, state, control, model=model, optimizer=optimizer)
    path = tmp_path / "full-model-audit.json"
    initial = json.loads(path.read_text())["initial_fingerprints"]
    model().square().sum().backward()
    callback.on_pre_optimizer_step(args, state, control, model=model, optimizer=optimizer)
    optimizer.step()
    optimizer.zero_grad()
    state.global_step = 1
    callback.on_step_end(args, state, control, model=model, optimizer=optimizer)
    callback.on_train_end(args, state, control, model=model, optimizer=optimizer)
    result = json.loads(path.read_text())
    assert result["first_update"]["global_step"] == 1
    assert result["first_update"]["gradients"]["all_finite"] is True
    assert result["first_update"]["gradients"]["tensor_count"] == 5
    assert result["first_update"]["optimizer_state"]["all_finite"] is True
    assert result["first_update"]["optimizer_state"]["dtypes"]["torch.float32"] == 15
    assert set(initial) == {"embedding", "attention", "mlp", "norm"}
    assert all(
        initial[key]["sha256"] != result["train_end_fingerprints"][key]["sha256"] for key in initial
    )
    resumed = module.FullModelAuditCallback()
    resumed.on_train_begin(args, state, control, model=model, optimizer=optimizer)
    assert json.loads(path.read_text())["initial_fingerprints"] == initial
    assert json.loads(path.read_text())["runs"][-1]["start_global_step"] == 1


def test_callback_rejects_missing_resume_evidence_and_nonfinite_gradient(tmp_path):
    from transformers import TrainerControl, TrainerState

    module = audit_module()
    model = TinyQwen()
    optimizer = torch.optim.AdamW(model.parameters())
    args = SimpleNamespace(output_dir=str(tmp_path))
    callback = module.FullModelAuditCallback()
    with pytest.raises(ValueError, match="resume.*initial"):
        callback.on_train_begin(
            args, TrainerState(global_step=3), TrainerControl(), model=model, optimizer=optimizer
        )
    state, control = TrainerState(), TrainerControl()
    callback.on_train_begin(args, state, control, model=model, optimizer=optimizer)
    model.model.embed_tokens.weight.grad = torch.full_like(
        model.model.embed_tokens.weight, float("nan")
    )
    with pytest.raises(ValueError, match="nonfinite gradient"):
        callback.on_pre_optimizer_step(args, state, control, model=model, optimizer=optimizer)


def test_callback_does_not_claim_skipped_optimizer_update_on_resume(tmp_path):
    from transformers import TrainerControl, TrainerState

    module = audit_module()
    model = TinyQwen()
    optimizer = torch.optim.AdamW(model.parameters())
    args = SimpleNamespace(output_dir=str(tmp_path))
    state, control = TrainerState(), TrainerControl()
    callback = module.FullModelAuditCallback()
    callback.on_train_begin(args, state, control, model=model, optimizer=optimizer)
    # Existing optimizer state alone does not prove the next native step performed an update.
    model().square().sum().backward()
    optimizer.step()
    optimizer.zero_grad()
    state.global_step = 1
    resumed = module.FullModelAuditCallback()
    resumed.on_train_begin(args, state, control, model=model, optimizer=optimizer)
    model().square().sum().backward()
    resumed.on_pre_optimizer_step(args, state, control, model=model, optimizer=optimizer)
    state.global_step = 2  # AMP skipped optimizer.step().
    resumed.on_step_end(args, state, control, model=model, optimizer=optimizer)
    assert json.loads((tmp_path / "full-model-audit.json").read_text())["first_update"] is None
    optimizer.step()
    state.global_step = 3
    resumed.on_step_end(args, state, control, model=model, optimizer=optimizer)
    assert (
        json.loads((tmp_path / "full-model-audit.json").read_text())["first_update"]["global_step"]
        == 3
    )


def test_prepare_rejects_supplied_truncation_before_writing_projection(tmp_path):
    recipe_path = ROOT / "experiments/finetuning/configs/full-0.6b.yaml"
    manifest = tmp_path / "source.json"
    manifest.write_text(json.dumps(corpus_fixture()), encoding="utf-8")
    lengths = {
        family + "-q:" + task: {"source_tokens": 20, "target_tokens": 10}
        for family in ("music", "fossil", "kite")
        for task in ("answer", "rewrite")
    }
    lengths["music-q:answer"]["source_tokens"] = 1020
    output = tmp_path / "projection"
    with pytest.raises(ValueError, match="truncation.*music-q:answer"):
        prepare(
            output,
            model_path="/model",
            runtime_root="/run",
            manifest_path=manifest,
            recipe_path=recipe_path,
            token_lengths=lengths,
        )
    assert not output.exists()


def test_training_arguments_register_full_audit_only_for_full():
    module = audit_module()
    budget = object()
    _, callbacks = factory_training_arguments(full_recipe(), "preflight", budget)
    assert any(isinstance(item, module.FullModelAuditCallback) for item in callbacks)
    _, callbacks = factory_training_arguments({"finetuning_type": "lora"}, "preflight", budget)
    assert callbacks == [budget]


FULL_IDENTITY = {
    "task_id": "todo-020",
    "model_hash": "a" * 64,
    "data_hash": "b" * 64,
    "recipe_hash": "c" * 64,
}


def full_checkpoint(tmp_path, *, sharded=False):
    """Actual small safetensors/tokenizer artifacts, never production model weights."""
    from safetensors.torch import save_file
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from transformers import PreTrainedTokenizerFast

    directory = tmp_path / "checkpoint-100"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps({"model_type": "qwen3"}))
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=Tokenizer(WordLevel({"[UNK]": 0, "hello": 1}, unk_token="[UNK]")),
        unk_token="[UNK]",
        chat_template="{% for message in messages %}{{ message['content'] }}{% endfor %}",
    )
    tokenizer.save_pretrained(directory)
    if sharded:
        save_file({"embedding.weight": torch.ones(2, 2)}, directory / "model-00001.safetensors")
        save_file({"norm.weight": torch.ones(2)}, directory / "model-00002.safetensors")
        (directory / "model.safetensors.index.json").write_text(
            json.dumps(
                {
                    "weight_map": {
                        "embedding.weight": "model-00001.safetensors",
                        "norm.weight": "model-00002.safetensors",
                    }
                }
            )
        )
    else:
        save_file({"embedding.weight": torch.ones(2, 2)}, directory / "model.safetensors")
    torch.save({"state": {}, "param_groups": []}, directory / "optimizer.pt")
    torch.save({"last_epoch": 100}, directory / "scheduler.pt")
    torch.save({"cpu": torch.get_rng_state()}, directory / "rng_state.pth")
    (directory / "trainer_state.json").write_text(
        json.dumps({"global_step": 100, "max_steps": 200, "log_history": [{"loss": 1.0}]})
    )
    return directory


def test_full_checkpoint_binds_complete_saved_model_and_external_template(tmp_path):
    directory = full_checkpoint(tmp_path)
    (directory / "full-model-audit.json").write_text("mutable external evidence")
    record = training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    assert {
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "chat_template.jinja",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
        "trainer_state.json",
    } == record["files"].keys()
    training.read_checkpoint(directory, FULL_IDENTITY)


@pytest.mark.parametrize("operation", ["mark", "resume"])
@pytest.mark.parametrize("extra_kind", ["default_template", "empty_directory", "file"])
def test_full_checkpoint_rejects_additional_template_inputs(tmp_path, operation, extra_kind):
    from transformers import PreTrainedTokenizerFast

    directory = full_checkpoint(tmp_path)
    if operation == "resume":
        record = training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    extra = directory / "additional_chat_templates"
    if extra_kind == "file":
        extra.write_text("unsupported template input")
    else:
        extra.mkdir()
        if extra_kind == "default_template":
            override = "OVERRIDE {{ messages[0]['content'] }}"
            (extra / "default.jinja").write_text(override)
            # The real installed loader prefers this unbound default to chat_template.jinja.
            loaded = PreTrainedTokenizerFast.from_pretrained(directory, local_files_only=True)
            assert loaded.chat_template == override
    with pytest.raises(ValueError, match="additional_chat_templates"):
        if operation == "resume":
            training.validate_resume(record, FULL_IDENTITY)
        else:
            training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    if operation == "mark":
        assert not (directory / "complete.json").exists()


def test_adapter_checkpoint_retains_existing_additional_template_behavior(tmp_path):
    directory = full_checkpoint(tmp_path)
    (directory / "model.safetensors").rename(directory / "adapter_model.safetensors")
    (directory / "adapter_config.json").write_text("{}")
    identity = {**FULL_IDENTITY, "task_id": "todo-019"}
    record = training.mark_checkpoint(directory, identity, 200, save_seconds=2)
    extra = directory / "additional_chat_templates"
    extra.mkdir()
    (extra / "default.jinja").write_text("legacy adapter template")
    training.validate_resume(record, identity)


@pytest.mark.parametrize(
    "missing",
    [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
        "trainer_state.json",
    ],
)
def test_full_checkpoint_rejects_missing_reload_or_resume_file(tmp_path, missing):
    directory = full_checkpoint(tmp_path)
    (directory / missing).unlink()
    with pytest.raises(ValueError, match=missing):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    assert not (directory / "complete.json").exists()


def test_full_checkpoint_requires_all_shards(tmp_path):
    directory = full_checkpoint(tmp_path, sharded=True)
    record = training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    assert {
        "model.safetensors.index.json",
        "model-00001.safetensors",
        "model-00002.safetensors",
    } <= record["files"].keys()
    (directory / "model-00002.safetensors").unlink()
    with pytest.raises(ValueError, match="model-00002"):
        training.read_checkpoint(directory, FULL_IDENTITY)


@pytest.mark.parametrize("field", ["task_id", "model_hash", "data_hash", "recipe_hash"])
def test_full_resume_rejects_base_or_recipe_change(tmp_path, field):
    record = training.mark_checkpoint(full_checkpoint(tmp_path), FULL_IDENTITY, 200, save_seconds=2)
    with pytest.raises(ValueError, match="identity"):
        training.validate_resume(record, {**FULL_IDENTITY, field: "changed"})


@pytest.mark.parametrize(
    "name",
    [
        "model.safetensors",
        "config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "chat_template.jinja",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
        "trainer_state.json",
        "special_tokens_map.json",
    ],
)
def test_full_resume_rejects_modified_files(tmp_path, name):
    directory = full_checkpoint(tmp_path)
    record = training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    with (directory / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="hash"):
        training.validate_resume(record, FULL_IDENTITY)


@pytest.mark.parametrize("broken", ["weights", "config", "tokenizer", "template", "index"])
def test_full_checkpoint_rejects_invalid_artifact_formats(tmp_path, broken):
    directory = full_checkpoint(tmp_path, sharded=broken == "index")
    name, payload = {
        "weights": ("model.safetensors", b"not safetensors"),
        "config": ("config.json", b"{}"),
        "tokenizer": ("tokenizer.json", b"{}"),
        "template": ("chat_template.jinja", b"   "),
        "index": ("model.safetensors.index.json", b'{"weight_map": {}}'),
    }[broken]
    (directory / name).write_bytes(payload)
    with pytest.raises(ValueError):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    assert not (directory / "complete.json").exists()


@pytest.mark.parametrize("name", ["../escape.safetensors", "model-00001.safetensors"])
def test_full_checkpoint_rejects_unsafe_or_wrong_shard_membership(tmp_path, name):
    directory = full_checkpoint(tmp_path, sharded=True)
    (tmp_path / "escape.safetensors").write_bytes(
        (directory / "model-00001.safetensors").read_bytes()
    )
    (directory / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"nonexistent.weight": name}})
    )
    with pytest.raises(ValueError):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)


def test_full_checkpoint_rejects_adapter_identity_even_when_full_weights_exist(tmp_path):
    directory = full_checkpoint(tmp_path)
    (directory / "adapter_model.safetensors").write_bytes(b"adapter")
    (directory / "adapter_config.json").write_text("{}")
    with pytest.raises(ValueError, match="adapter"):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)


def test_full_task_rejects_adapter_only_checkpoint(tmp_path):
    directory = full_checkpoint(tmp_path)
    (directory / "model.safetensors").rename(directory / "adapter_model.safetensors")
    (directory / "adapter_config.json").write_text("{}")
    with pytest.raises(ValueError, match="adapter"):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)


@pytest.mark.parametrize(
    "name",
    [
        "adapter_config.json",
        "adapter_model.bin",
        "pytorch_model.bin",
        "pytorch_model.bin.index.json",
    ],
)
def test_full_checkpoint_rejects_alternate_loader_inputs(tmp_path, name):
    # Trainer can choose a .bin instead of the indexed safetensors; from_pretrained
    # treats adapter_config as a redirect. None may silently bypass the manifest.
    directory = full_checkpoint(tmp_path, sharded=True)
    (directory / name).write_bytes(b"alternate unbound loader input")
    with pytest.raises(ValueError):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)


@pytest.mark.parametrize(
    "name",
    [
        "generation_config.json",
        "added_tokens.json",
        "vocab.json",
        "merges.txt",
        "training_args.bin",
    ],
)
def test_full_resume_binds_optional_loader_files_when_present(tmp_path, name):
    directory = full_checkpoint(tmp_path)
    (directory / name).write_bytes(b"original optional artifact")
    record = training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)
    assert name in record["files"]
    (directory / name).write_bytes(b"modified optional artifact")
    with pytest.raises(ValueError, match="hash"):
        training.validate_resume(record, FULL_IDENTITY)
    (directory / name).unlink()
    with pytest.raises(ValueError, match="manifest"):
        training.validate_resume(record, FULL_IDENTITY)


def test_full_checkpoint_rejects_ambiguous_single_and_sharded_weights(tmp_path):
    from safetensors.torch import save_file

    directory = full_checkpoint(tmp_path, sharded=True)
    save_file({"different.weight": torch.zeros(2)}, directory / "model.safetensors")
    with pytest.raises(ValueError, match="Ambiguous"):
        training.mark_checkpoint(directory, FULL_IDENTITY, 200, save_seconds=2)


def test_full_task_rejects_lora_recipe_before_budget_start(tmp_path):
    model, data = tmp_path / "model", tmp_path / "data"
    model.mkdir()
    data.mkdir()
    (model / "config.json").write_text("{}")
    (data / "train.json").write_text("[]")
    (data / "dataset_info.json").write_text(json.dumps({"train": {"file_name": "train.json"}}))
    with pytest.raises(ValueError, match="full"):
        training.training_identity(
            "todo-020",
            {
                "finetuning_type": "lora",
                "model_name_or_path": str(model),
                "dataset_dir": str(data),
                "dataset": "train",
            },
        )
