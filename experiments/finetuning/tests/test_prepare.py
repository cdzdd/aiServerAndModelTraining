import hashlib
import json
import os
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
    # Frozen v1 teaching content is the same across native newline conventions.
    for filename, expected in {
        "dataset_info.json": "863095269dfa2ff287ab9b6123fa4e8d831a5c675b0087b59273d019331ab9a4",
        "train.json": "90cc64afb506f734194741516da21d618fd7689c8bb2d98ed4ec48e0c0743261",
        "validation.json": "ef50dc0bddda43a52ca144fb37333246cf4f77b725b144a899d07224cb6f06a7",
    }.items():
        assert (
            hashlib.sha256((tmp_path / filename).read_text(encoding="utf-8").encode()).hexdigest()
            == expected
        )
    if os.name != "nt":
        return
    # These exact byte hashes were recorded from the unchanged Windows v1 baseline.
    assert first["files_sha256"] == {
        "dataset_info.json": "24e1f260c76df52ff64f6c1348f62a672b1db23616ebfd903f06585fff539262",
        "manifest.json": "024255b602eb9a7b69089431ff5966a68540f07403c06c0ae75a2cf1e4cb66ec",
        "train.json": "662390ae3ff7e5f899a84d4144c8790dde286bfcac681f54369a5292ec15aefd",
        "validation.json": "655130653a25a3187d7782c4731c0244cb119c28714f662d27ba335f0e987493",
    }
