"""Runtime full-parameter checks and bounded evidence for the todo-020 experiment."""

import hashlib
import json
from collections import Counter
from pathlib import Path

BASE_REPOSITORY = "Qwen/Qwen3-0.6B"
BASE_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"


def validate_full_recipe(recipe):
    forbidden = [
        key
        for key in recipe
        if key.startswith(("lora", "adapter", "quantization", "freeze"))
        or key in {"double_quantization", "use_dora", "use_rslora", "additional_target"}
    ]
    if forbidden:
        raise ValueError(f"full recipe forbids adapter/quantization/freeze fields: {forbidden}")
    if recipe.get("model_revision") != BASE_REVISION:
        raise ValueError("full recipe requires the pinned Qwen3-0.6B model_revision")
    if (
        recipe.get("optim") != "adamw_torch"
        or recipe.get("pure_bf16") is not False
        or recipe.get("trust_remote_code") is not False
        or recipe.get("save_only_model") is not False
        or recipe.get("restore_callback_states_from_checkpoint") is not True
    ):
        raise ValueError("full recipe requires AdamW, mixed BF16 and restorable callback state")
    if (
        recipe.get("save_strategy") != "steps"
        or recipe.get("eval_strategy") != "steps"
        or type(recipe.get("save_steps")) is not int
        or recipe["save_steps"] <= 0
        or recipe["save_steps"] != recipe.get("eval_steps")
        or recipe["save_steps"] > recipe["max_steps"]
    ):
        raise ValueError("full recipe requires aligned in-training save/eval steps")


def optimizer_state_summary(optimizer):
    import torch

    dtypes, count, finite = Counter(), 0, True
    for values in optimizer.state.values():
        for value in values.values():
            if torch.is_tensor(value):
                count += 1
                dtypes[str(value.dtype)] += 1
                finite = finite and bool(torch.isfinite(value).all().item())
    return {"tensor_count": count, "dtypes": dict(dtypes), "all_finite": finite}


def audit_full_model(model, optimizer):
    """Count actual unique Parameter objects; reject frozen, adapted or quantized runs."""
    for name, module in model.named_modules():
        classes = [f"{base.__module__}.{base.__name__}".lower() for base in type(module).__mro__]
        if any("peft." in cls or "lora" in cls for cls in classes) or any(
            hasattr(module, field) for field in ("lora_A", "lora_B", "peft_config")
        ):
            raise ValueError(f"full model contains adapter module: {name}")
        if (
            any(
                "bitsandbytes." in cls or ".quantized." in cls or "quantlinear" in cls
                for cls in classes
            )
            or any(
                bool(getattr(module, field, False))
                for field in ("is_quantized", "is_loaded_in_4bit", "is_loaded_in_8bit")
            )
            or any(hasattr(module, field) for field in ("qweight", "quant_state"))
        ):
            raise ValueError(f"full model contains quantized module: {name}")
    parameters = {id(param): (name, param) for name, param in model.named_parameters()}
    if not parameters:
        raise ValueError("full model has no parameters")
    for name, param in parameters.values():
        if not param.requires_grad:
            raise ValueError(f"full model contains frozen parameter: {name}")
        if not param.is_floating_point() or getattr(param, "quant_state", None) is not None:
            raise ValueError(f"full model contains quantized parameter: {name}")
    optimizer_params = {
        id(param): param for group in optimizer.param_groups for param in group["params"]
    }
    if set(optimizer_params) != set(parameters):
        raise ValueError("optimizer parameters must cover exactly the full model parameters")
    layers, dtypes = {}, Counter()
    for name, param in parameters.values():
        parts = name.split(".")
        layer = ".".join(parts[:3]) if parts[:2] == ["model", "layers"] else name.rsplit(".", 1)[0]
        stats = layers.setdefault(layer, {"parameters": 0, "parameter_tensors": 0, "dtypes": {}})
        stats["parameters"] += param.numel()
        stats["parameter_tensors"] += 1
        dtype = str(param.dtype)
        stats["dtypes"][dtype] = stats["dtypes"].get(dtype, 0) + param.numel()
        dtypes[dtype] += param.numel()
    total = sum(param.numel() for _, param in parameters.values())
    return {
        "total_parameters": total,
        "trainable_parameters": total,
        "optimizer_parameters": sum(param.numel() for param in optimizer_params.values()),
        "parameter_tensors": len(parameters),
        "trainable_parameter_tensors": len(parameters),
        "optimizer_parameter_tensors": len(optimizer_params),
        "parameter_dtypes": dict(dtypes),
        "layers": layers,
        "optimizer_state": optimizer_state_summary(optimizer),
    }


def audit_full_token_lengths(samples, token_lengths, cutoff_len):
    """Check complete, untruncated template source/target counts supplied by an operator.

    This length-table check cannot prove the tokenizer identity or actual collator masks.
    """
    ids = [sample["id"] for sample in samples]
    if len(set(ids)) != len(ids) or set(ids) != set(token_lengths):
        raise ValueError("token lengths must cover the exact unique projection sample inventory")
    if type(cutoff_len) is not int or cutoff_len <= 0:
        raise ValueError("cutoff_len must be a positive integer")
    counts = {}
    for sample in samples:
        item = token_lengths[sample["id"]]
        if not isinstance(item, dict) or set(item) != {"source_tokens", "target_tokens"}:
            raise ValueError("token lengths require source_tokens and target_tokens")
        source, target = item["source_tokens"], item["target_tokens"]
        if any(type(value) is not int or value <= 0 for value in (source, target)):
            raise ValueError("source/target token lengths must be positive integers")
        if source + target > cutoff_len:
            raise ValueError(f"target or evidence truncation is forbidden: {sample['id']}")
        stats = counts.setdefault(
            sample["split"],
            {
                "samples": 0,
                "max_source": 0,
                "max_target": 0,
                "max_total": 0,
            },
        )
        stats["samples"] += 1
        stats["max_source"] = max(stats["max_source"], source)
        stats["max_target"] = max(stats["max_target"], target)
        stats["max_total"] = max(stats["max_total"], source + target)
    return {"status": "lengths_verified_pending_collator_masks", "counts": counts}


def representative_fingerprints(model):
    import torch

    parameters = dict(model.named_parameters())
    names = {
        "embedding": "model.embed_tokens.weight",
        "attention": "model.layers.0.self_attn.q_proj.weight",
        "mlp": "model.layers.0.mlp.down_proj.weight",
        "norm": "model.layers.0.input_layernorm.weight",
    }
    result = {}
    for kind, name in names.items():
        if name not in parameters:
            raise ValueError(f"missing Qwen3 representative parameter: {name}")
        param = parameters[name]
        # One complete representative at a time; never copy all model weights or emit raw values.
        raw = param.detach().contiguous().view(torch.uint8).cpu().numpy()
        result[kind] = {
            "name": name,
            "shape": list(param.shape),
            "dtype": str(param.dtype),
            "bytes": param.numel() * param.element_size(),
            "sha256": hashlib.sha256(memoryview(raw).cast("B")).hexdigest(),
        }
    return result


class FullModelAuditCallback:
    """TrainerCallback mixin, registered only for full training inside the owned worker."""

    def __init__(self):
        self.record = None
        self.gradients = None

    def publish(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)

    def on_train_begin(self, args, state, control, model=None, optimizer=None, **kwargs):
        audit = audit_full_model(model, optimizer)
        self.path = Path(args.output_dir) / "full-model-audit.json"
        if state.global_step:
            if not self.path.is_file():
                raise ValueError("resume requires original initial fingerprint evidence")
            self.record = json.loads(self.path.read_text(encoding="utf-8"))
            if not self.record.get("initial_fingerprints"):
                raise ValueError("resume requires original initial fingerprint evidence")
        else:
            if self.path.exists():
                raise ValueError("fresh training must not overwrite original full audit evidence")
            self.record = {
                "schema_version": 1,
                "kind": "full",
                "initial_fingerprints": representative_fingerprints(model),
                "initial_global_step": 0,
                "first_update": None,
                "runs": [],
            }
        self.record["runs"].append(
            {
                "start_global_step": state.global_step,
                "end_global_step": None,
                "start_audit": audit,
            }
        )
        self.start_step = state.global_step
        self.start_optimizer_steps = {
            id(param): float(values.get("step", 0)) for param, values in optimizer.state.items()
        }
        self.publish()

    def on_pre_optimizer_step(self, args, state, control, model=None, **kwargs):
        if self.record["first_update"] is not None:
            return
        import torch

        dtypes, count, finite = Counter(), 0, True
        for param in model.parameters():
            if param.grad is not None:
                count += 1
                dtypes[str(param.grad.dtype)] += 1
                finite = finite and bool(torch.isfinite(param.grad).all().item())
        self.gradients = {"tensor_count": count, "dtypes": dict(dtypes), "all_finite": finite}
        if not finite or not count:
            raise ValueError(
                "full update requires finite gradients; nonfinite gradient or no gradients"
            )

    def on_step_end(self, args, state, control, model=None, optimizer=None, **kwargs):
        if self.record["first_update"] is not None or state.global_step <= self.start_step:
            return
        # Native global_step can also advance on a skipped AMP update: require real Adam state.
        if not any(
            float(values.get("step", 0)) > self.start_optimizer_steps.get(id(param), 0)
            for param, values in optimizer.state.items()
        ):
            return
        summary = optimizer_state_summary(optimizer)
        if not summary["all_finite"]:
            raise ValueError("nonfinite AdamW optimizer state")
        if self.gradients is None:
            raise ValueError("first full update is missing gradient evidence")
        self.record["first_update"] = {
            "global_step": state.global_step,
            "gradients": self.gradients,
            "optimizer_state": summary,
            "fingerprints": representative_fingerprints(model),
        }
        self.publish()

    def on_train_end(self, args, state, control, model=None, optimizer=None, **kwargs):
        self.record["runs"][-1]["end_global_step"] = state.global_step
        self.record["train_end_global_step"] = state.global_step
        self.record["train_end_optimizer_state"] = optimizer_state_summary(optimizer)
        self.record["train_end_fingerprints"] = representative_fingerprints(model)
        self.record["train_end_model_scope"] = (
            "Trainer in-memory model; best may already be restored; not final checkpoint identity"
        )
        self.publish()
