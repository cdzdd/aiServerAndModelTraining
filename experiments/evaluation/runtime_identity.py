"""Shared runtime identity checks without database or model runtime dependencies."""

import hashlib
import re

from app.modules.rag.prompts import ANSWER_SYSTEM, REWRITE_SYSTEM

GENERAL_SYSTEM = "按用户要求完成任务，严格遵守要求的输出格式。"


def prompt_hashes():
    return {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in {
            "answer": ANSWER_SYSTEM,
            "rewrite": REWRITE_SYSTEM,
            "general": GENERAL_SYSTEM,
        }.items()
    }


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _model_files(files):
    required = {"config.json", "tokenizer.json", "tokenizer_config.json"}
    allowed = required | {
        "generation_config.json",
        "tokenizer.model",
        "special_tokens_map.json",
        "added_tokens.json",
        "vocab.json",
        "merges.txt",
        "chat_template.jinja",
        "model.safetensors",
        "model.safetensors.index.json",
    }
    if not isinstance(files, dict) or not required <= files.keys():
        raise ValueError("runtime requires actual model files")
    shards = {}
    totals = set()
    for name, digest in files.items():
        if not isinstance(name, str) or not _digest(digest):
            raise ValueError("runtime model files require bare names and SHA256")
        shard = re.fullmatch(r"model-(\d{5})-of-(\d{5})\.safetensors", name)
        if shard:
            index, total = map(int, shard.groups())
            shards[index] = name
            totals.add(total)
        elif name not in allowed:
            raise ValueError("runtime model files require known bare filenames")
    if "model.safetensors" in files:
        if shards or "model.safetensors.index.json" in files:
            raise ValueError("runtime model files mix sharded and unsharded weights")
    elif (
        len(totals) != 1
        or "model.safetensors.index.json" not in files
        or set(shards) != set(range(1, next(iter(totals), 0) + 1))
    ):
        raise ValueError("runtime model files require complete weights and shard index")
    return dict(files)
