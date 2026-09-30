import json
from pathlib import Path

from experiments.finetuning.prepare_data import prepare


def test_prepare_writes_only_grounded_train_and_independent_validation(tmp_path):
    root = Path(__file__).resolve().parents[3]
    prepare(tmp_path, model_path="/models/qwen", runtime_root="/runs/demo", root=root)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    train = json.loads((tmp_path / "train.json").read_text(encoding="utf-8"))
    validation = json.loads((tmp_path / "validation.json").read_text(encoding="utf-8"))
    assert len(train) == 8
    assert len(validation) == 2
    assert {
        sample["group"] for sample in manifest["samples"] if sample["split"] == "validation"
    } == {"validation-newspaper"}
    assert all(set(sample) == {"messages"} for sample in train + validation)
    assert json.loads(train[0]["messages"][2]["content"])["selections"] == [
        {"index": 1, "quote": "车牌号和学生编号"}
    ]
    assert "checkpoint-2" in (tmp_path / "configs/qlora-resume.yaml").read_text(encoding="utf-8")


def test_repeated_preparation_keeps_content_hashes_identical(tmp_path):
    root = Path(__file__).resolve().parents[3]
    first = prepare(tmp_path, model_path="/models/qwen", runtime_root="/runs/demo", root=root)
    second = prepare(tmp_path, model_path="/models/qwen", runtime_root="/runs/demo", root=root)
    assert first == second
