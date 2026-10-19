# ruff: noqa: E402
"""Preserve fixed v1 teaching data; project only explicitly provided corpus v2."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from experiments.finetuning.validate_data import validate_corpus, validate_manifest

from app.modules.rag.prompts import ANSWER_SYSTEM, PROMPT_VERSION, REWRITE_SYSTEM

VALIDATION_TEXT = (
    "XB-65教学校报只接受校园活动报道，投稿须包含标题与作者署名，"
    "稿件通过校报邮箱xb65@news.invalid提交。"
)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(
    output,
    *,
    model_path,
    runtime_root,
    root=ROOT,
    manifest_path=None,
    recipe_path=None,
    token_lengths=None,
):
    if manifest_path is None and recipe_path is None:
        return _prepare_v1(output, model_path=model_path, runtime_root=runtime_root, root=root)
    if manifest_path is None or recipe_path is None:
        raise ValueError("v2 preparation requires both explicit manifest_path and recipe_path")
    return _prepare_v2(
        output,
        model_path=model_path,
        runtime_root=runtime_root,
        manifest_path=manifest_path,
        recipe_path=recipe_path,
        token_lengths=token_lengths,
    )


def _prepare_v2(
    output, *, model_path, runtime_root, manifest_path, recipe_path, token_lengths=None
):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite nonempty frozen output directory")
    corpus = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    stats = validate_corpus(corpus)
    recipe = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8-sig"))
    if not isinstance(recipe, dict) or not recipe.get("model_revision"):
        raise ValueError("explicit recipe with immutable model_revision required")
    full = recipe.get("finetuning_type") == "full"
    if full:
        from experiments.finetuning.audit_full_model import validate_full_recipe

        validate_full_recipe(recipe)
    sources = {source["id"]: source for source in corpus["sources"]}
    samples = []
    for case in corpus["cases"]:
        data = {
            "question": case["question"],
            "retrieval_query": case["retrieval_query"],
            "evidence": [
                {
                    "index": item["index"],
                    "title": sources[item["source_id"]]["title"],
                    "text": sources[item["source_id"]]["text"],
                }
                for item in case["evidence"]
            ],
        }
        tasks = [("answer", ANSWER_SYSTEM, data, case["answer"])]
        if case.get("rewrite") is not None:
            tasks.append(
                (
                    "rewrite",
                    REWRITE_SYSTEM,
                    {"question": case["question"], "history": case["history"]},
                    case["rewrite"],
                )
            )
        for task, system, user, target in tasks:
            samples.append(
                {
                    "id": case["id"] + ":" + task,
                    "case_id": case["id"],
                    "task": task,
                    "source_id": case["source_id"],
                    "group": case["group"],
                    "family": case["family"],
                    "split": case["split"],
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
                        },
                        {
                            "role": "assistant",
                            "content": json.dumps(
                                target, ensure_ascii=False, separators=(",", ":")
                            ),
                        },
                    ],
                }
            )
    token_audit = {"status": "pending_actual_frozen_tokenizer", "counts": None}
    if full and token_lengths is not None:
        from experiments.finetuning.audit_full_model import audit_full_token_lengths

        token_audit = audit_full_token_lengths(samples, token_lengths, recipe["cutoff_len"])
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "manifest-v2.json", dict(corpus, samples=samples))
    for split, filename in (("train", "train.json"), ("dev", "validation.json")):
        write_json(
            output / filename,
            [{"messages": sample["messages"]} for sample in samples if sample["split"] == split],
        )
    info = {}
    for name, filename in (
        ("teaching_train", "train.json"),
        ("teaching_validation", "validation.json"),
    ):
        info[name] = {
            "file_name": filename,
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }
    write_json(output / "dataset_info.json", info)
    write_json(
        output / "evaluation-v2.json",
        {
            "schema_version": 2,
            "version": corpus["version"],
            "synthetic": True,
            "human_reviewed": False,
            "prompt_version": PROMPT_VERSION,
            "review_status": (
                "author rule checks; independent review pending; no human business review"
            ),
            "sources": [source for source in corpus["sources"] if source["split"] != "train"],
            "cases": [case for case in corpus["cases"] if case["split"] != "train"],
        },
    )
    write_json(output / "general-regression.json", corpus["general_regression"])
    configs = output / "configs"
    configs.mkdir()
    recipe.update(
        model_name_or_path=model_path,
        dataset_dir=runtime_root,
        output_dir=runtime_root + "/train",
    )
    train_filename = "full-train.yaml" if full else "qlora-train.yaml"
    (configs / train_filename).write_text(yaml.safe_dump(recipe), encoding="utf-8")
    infer = {
        key: recipe[key]
        for key in (
            "model_name_or_path",
            "model_revision",
            "trust_remote_code",
            "quantization_method",
            "quantization_bit",
            "quantization_type",
            "double_quantization",
            "template",
            "flash_attn",
        )
        if key in recipe
    }
    infer.update(
        infer_backend="huggingface",
        infer_dtype="bfloat16",
        finetuning_type="full" if full else "lora",
        do_sample=False,
        max_new_tokens=512,
    )
    for name in ("base", "finetuned"):
        config = dict(infer)
        if name == "finetuned":
            if full:
                config["model_name_or_path"] = runtime_root + "/train"
            else:
                config["adapter_name_or_path"] = runtime_root + "/train"
        (configs / f"inference-{name}.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    files = {
        str(path.relative_to(output)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    summary = {
        "schema_version": 2,
        "version": corpus["version"],
        "synthetic": True,
        "human_reviewed": False,
        "statistics": stats,
        "files_sha256": files,
        "input_manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        "recipe_sha256": hashlib.sha256(Path(recipe_path).read_bytes()).hexdigest(),
        "prompt_sha256": {
            "answer": hashlib.sha256(ANSWER_SYSTEM.encode()).hexdigest(),
            "rewrite": hashlib.sha256(REWRITE_SYSTEM.encode()).hexdigest(),
        },
        "sample_inventory": [
            {
                "id": sample["id"],
                "split": sample["split"],
                "task": sample["task"],
                "utf8_bytes": sum(len(m["content"].encode()) for m in sample["messages"]),
                "sha256": hashlib.sha256(
                    json.dumps(
                        sample["messages"], ensure_ascii=False, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "tokens": None,
            }
            for sample in samples
        ],
        "token_audit": token_audit,
        "review": {
            "author_rule_checked": True,
            "independent_review": "pending",
            "human_reviewed": False,
        },
    }
    write_json(output / "data-summary.json", summary)
    return summary


def _prepare_v1(output, *, model_path, runtime_root, root=ROOT):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    training_path = root / "experiments/evaluation/training.json"
    evaluation_path = root / "experiments/evaluation/dataset.json"
    original = json.loads(training_path.read_text(encoding="utf-8-sig"))
    sources = original["sources"] + [
        {
            "id": "validation-newspaper",
            "group": "validation-newspaper",
            "split": "validation",
            "title": "教学校报投稿XB-65",
            "text": VALIDATION_TEXT,
            "provenance": "本项目原创虚构教学资料；邮箱使用.invalid保留域",
            "sha256": hashlib.sha256(VALIDATION_TEXT.encode()).hexdigest(),
        }
    ]
    cases = original["cases"] + [
        {
            "id": "validation-newspaper-q1",
            "group": "validation-newspaper",
            "split": "validation",
            "question": "XB-65教学校报接收哪些题材的稿件？",
            "reference_sources": ["validation-newspaper"],
            "reference_answer": "校园活动报道",
        },
        {
            "id": "validation-newspaper-q2",
            "group": "validation-newspaper",
            "split": "validation",
            "question": "向XB-65教学校报投稿必须包含哪些信息？",
            "reference_sources": ["validation-newspaper"],
            "reference_answer": "标题与作者署名",
        },
    ]
    by_id = {source["id"]: source for source in sources}
    samples = []
    for case in cases:
        source = by_id[case["reference_sources"][0]]
        user = {
            "question": case["question"],
            "retrieval_query": case["question"],
            "evidence": [{"index": 1, "title": source["title"], "text": source["text"]}],
        }
        answer = {
            "status": "answered",
            "selections": [{"index": 1, "quote": case["reference_answer"]}],
        }
        samples.append(
            {
                "id": case["id"],
                "split": case["split"],
                "group": case["group"],
                "source_id": source["id"],
                "question": case["question"],
                "messages": [
                    {"role": "system", "content": ANSWER_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(answer, ensure_ascii=False, separators=(",", ":")),
                    },
                ],
            }
        )
    manifest = {
        "version": "campus-qlora-teaching-v1",
        "synthetic": True,
        "human_reviewed": False,
        "prompt_version": PROMPT_VERSION,
        "training_fixture_sha256": hashlib.sha256(training_path.read_bytes()).hexdigest(),
        "evaluation_sha256": hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
        "sources": sources,
        "samples": samples,
    }
    stats = validate_manifest(manifest, json.loads(evaluation_path.read_text(encoding="utf-8-sig")))
    write_json(output / "manifest.json", manifest)
    for split, filename in [("train", "train.json"), ("validation", "validation.json")]:
        write_json(
            output / filename,
            [{"messages": sample["messages"]} for sample in samples if sample["split"] == split],
        )
    info = {}
    for dataset, filename in [
        ("teaching_train", "train.json"),
        ("teaching_validation", "validation.json"),
    ]:
        info[dataset] = {
            "file_name": filename,
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }
    write_json(output / "dataset_info.json", info)
    configs = output / "configs"
    configs.mkdir(exist_ok=True)
    common = yaml.safe_load((root / "experiments/finetuning/configs/recipe.yaml").read_text())
    common.update(model_name_or_path=model_path, dataset_dir=runtime_root)
    for name, steps, directory in [
        ("smoke", 2, "smoke"),
        ("resume", 4, "smoke"),
        ("train", 20, "train"),
    ]:
        config = dict(common, max_steps=steps, output_dir=runtime_root + "/" + directory)
        if name == "resume":
            config["resume_from_checkpoint"] = runtime_root + "/smoke/checkpoint-2"
        (configs / f"qlora-{name}.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    infer = {
        key: common[key]
        for key in [
            "model_name_or_path",
            "model_revision",
            "trust_remote_code",
            "quantization_method",
            "quantization_bit",
            "quantization_type",
            "double_quantization",
            "template",
            "flash_attn",
        ]
    }
    infer.update(
        infer_backend="huggingface",
        infer_dtype="bfloat16",
        finetuning_type="lora",
        do_sample=False,
        max_new_tokens=512,
    )
    for name in ("base", "finetuned"):
        config = dict(infer)
        if name == "finetuned":
            config["adapter_name_or_path"] = runtime_root + "/train"
        (configs / f"inference-{name}.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.glob("*.json"))
        if p.name != "data-summary.json"
    }
    summary = {
        "version": manifest["version"],
        "synthetic": True,
        "human_reviewed": False,
        "statistics": stats,
        "files_sha256": files,
        "prompt_sha256": hashlib.sha256(ANSWER_SYSTEM.encode()).hexdigest(),
    }
    write_json(output / "data-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/finetuning")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--manifest", type=Path, help="Explicit corpus v2 manifest")
    parser.add_argument("--recipe", type=Path, help="Explicit immutable-model v2 recipe")
    parser.add_argument(
        "--runtime-root",
        required=True,
        help="Path to the output directory as seen inside WSL",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.output,
                model_path=args.model_path,
                runtime_root=args.runtime_root,
                manifest_path=args.manifest,
                recipe_path=args.recipe,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
