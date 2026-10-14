import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.finetuning import run_training as training


class Clock:
    def __init__(self):
        self.wall = 1000.0
        self.mono = 0.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


IDENTITY = {
    "task_id": "todo-019",
    "model_hash": "a" * 64,
    "data_hash": "b" * 64,
    "recipe_hash": "c" * 64,
}


@pytest.fixture
def budget(tmp_path):
    path = tmp_path / "todo-019.json"
    training.initialize_budget(path, "todo-019")
    return path


def test_remaining_seconds():
    assert training.remaining_seconds(3600, 7200, 86400) == 75600
    assert training.remaining_seconds(86400, 1, 86400) == 0


def test_budget_counts_preflight_and_failures(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.advance(600)
        ledger.finish("worker_failed")
        ledger.start(IDENTITY, "formal")
        clock.advance(1200)
        ledger.finish("paused")
        assert ledger.record["occupied_seconds"] == 1800
        assert [x["reason"] for x in ledger.record["attempts"]] == ["worker_failed", "paused"]


def test_resume_preserves_consumed_time(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.advance(3600)
        ledger.finish("paused")
    clock.advance(5000)  # A closed attempt releases the GPU; this gap is free.
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.advance(7200)
        ledger.finish("completed")
        assert ledger.remaining == 75600


def test_output_change_cannot_reset_task_budget(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start({**IDENTITY, "output_dir": "first"}, "preflight")
        clock.advance(100)
        ledger.finish("worker_failed")
        ledger.start({**IDENTITY, "output_dir": "second"}, "formal")
        assert ledger.remaining == 86300
        ledger.finish("worker_failed")


def fake_repository(tmp_path):
    repo = tmp_path / "checkout"
    common = tmp_path / "main" / ".git"
    admin = common / "worktrees" / "checkout"
    admin.mkdir(parents=True)
    repo.mkdir()
    (repo / ".git").write_text(f"gitdir: {admin.as_posix()}")
    (admin / "commondir").write_text("../..")
    path = common / "codex-coordination/training-budgets/todo-019.json"
    claim = common / "codex-coordination/claims/todo-019.json"
    claim.parent.mkdir(parents=True)
    claim.write_text(
        json.dumps(
            {
                "task_id": "todo-019",
                "training_budget_path": str(path),
                "training_budget_seconds": 86400,
            }
        )
    )
    return repo, path


def test_budget_file_change_is_rejected(tmp_path):
    repo, path = fake_repository(tmp_path)
    assert training.resolve_budget_file("todo-019", path, 86400, repo) == path.resolve()
    with pytest.raises(ValueError, match="canonical"):
        training.resolve_budget_file("todo-019", tmp_path / "new.json", 86400, repo)


def test_budget_above_86400_is_rejected(tmp_path):
    repo, path = fake_repository(tmp_path)
    with pytest.raises(ValueError, match="86400"):
        training.resolve_budget_file("todo-019", path, 86401, repo)


def test_expired_budget_rejects_launch(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.advance(86400)
        ledger.finish("deadline")
        with pytest.raises(ValueError, match="exhausted"):
            ledger.start(IDENTITY, "formal")


def test_deleted_ledger_cannot_be_initialized_again(budget):
    budget.unlink()
    with pytest.raises(ValueError, match="initialized"):
        training.initialize_budget(budget, "todo-019")


def test_corrupt_ledger_blocks_resume(budget):
    budget.write_text('{"occupied_seconds": 0}')
    with pytest.raises(ValueError, match="ledger"):
        with training.BudgetLedger(budget, "todo-019"):
            pass


def test_optimized_python_cannot_disable_ledger_validation(budget):
    record = json.loads(budget.read_text())
    record["budget_seconds"] = 999999
    budget.write_text(json.dumps(record))
    script = (
        "from experiments.finetuning.run_training import BudgetLedger\n"
        f"with BudgetLedger({str(budget)!r}, 'todo-019'): pass\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "ledger" in result.stderr


def test_missing_parent_identity_blocks_recovery(budget):
    with training.BudgetLedger(budget, "todo-019") as ledger:
        ledger.start(IDENTITY, "preflight")
    record = json.loads(budget.read_text())
    record["attempts"][-1]["parent"] = None
    budget.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="owner|ledger"):
        with training.BudgetLedger(budget, "todo-019"):
            pass


def test_finish_refuses_to_stop_counting_while_worker_alive(budget):
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with training.BudgetLedger(budget, "todo-019") as ledger:
            ledger.start(IDENTITY, "preflight")
            ledger.active["worker"] = training.process_identity(worker.pid)
            with pytest.raises(ValueError, match="worker"):
                ledger.finish("paused")
            assert ledger.active is not None
            worker.kill()
            worker.wait(timeout=5)
            ledger.finish("worker_failed")
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)


def test_single_writer_is_enforced(budget):
    with training.BudgetLedger(budget, "todo-019"):
        with pytest.raises(ValueError, match="writer"):
            with training.BudgetLedger(budget, "todo-019"):
                pass


def test_utc_rollback_rejects_accounting(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.wall -= 1
        clock.mono += 1
        with pytest.raises(ValueError, match="clock"):
            ledger.heartbeat()


def test_suspend_or_forward_clock_jump_never_refunds_occupied_time(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.wall += 100
        clock.mono += 2
        ledger.finish("paused")
        assert ledger.record["occupied_seconds"] == 100


def test_utc_rollback_blocks_crash_recovery(budget):
    clock = Clock()
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
    clock.wall -= 1
    with pytest.raises(ValueError, match="clock"):
        with training.BudgetLedger(budget, "todo-019", clock=clock):
            pass


def test_crashed_attempt_counts_unobserved_interval(budget):
    clock = Clock()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    dead_owner = training.process_identity(child.pid)
    child.kill()
    child.wait(timeout=5)
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        ledger.start(IDENTITY, "preflight")
        clock.advance(10)
        ledger.heartbeat()
    record = json.loads(budget.read_text())
    record["attempts"][-1]["parent"] = dead_owner
    budget.write_text(json.dumps(record))
    clock.advance(90)
    with training.BudgetLedger(budget, "todo-019", clock=clock) as ledger:
        assert ledger.record["occupied_seconds"] == 100
        assert ledger.record["attempts"][-1]["reason"] == "recovered_crash"


def test_live_or_unknown_owner_blocks_recovery(budget):
    with training.BudgetLedger(budget, "todo-019") as ledger:
        ledger.start(IDENTITY, "preflight")
    with pytest.raises(ValueError, match="owner"):
        with training.BudgetLedger(budget, "todo-019"):
            pass


def test_save_hang_hits_deadline():
    started = time.monotonic()
    worker = training.OwnedWorker([sys.executable, "-c", "import time; time.sleep(30)"])
    result = worker.wait_until(time.monotonic() + 0.25)
    assert result == "deadline"
    assert worker.process.poll() is not None
    assert time.monotonic() - started < 3


def test_deadline_is_armed_before_parent_bookkeeping():
    worker = training.OwnedWorker(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        deadline=time.monotonic() + 0.15,
    )
    time.sleep(0.4)  # Simulates a slow ledger flush before the parent enters its monitor loop.
    try:
        assert worker.process.poll() is not None
        assert worker.wait_until(time.monotonic() + 30) == "deadline"
    finally:
        if worker.process.poll() is None:
            worker.stop(worker.process)


def test_expired_deadline_does_not_spawn_worker(tmp_path):
    touched = tmp_path / "launched"
    with pytest.raises(ValueError, match="deadline"):
        training.OwnedWorker(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(touched)!r}).touch()"],
            deadline=time.monotonic() - 1,
        )
    assert not touched.exists()


def test_forward_wall_clock_jump_also_enforces_external_deadline(monkeypatch):
    offset = [0]
    monkeypatch.setattr(
        training,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic,
            sleep=time.sleep,
            time=lambda: time.time() + offset[0],
        ),
    )
    worker = training.OwnedWorker(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        deadline=time.monotonic() + 20,
    )
    try:
        offset[0] = 30
        time.sleep(0.3)
        assert worker.process.poll() is not None
        assert worker.wait_until(time.monotonic() + 20) == "deadline"
    finally:
        if worker.process.poll() is None:
            worker.stop(worker.process)


@pytest.mark.skipif(os.name != "posix", reason="PDEATHSIG is a Linux/WSL safeguard")
def test_linux_worker_dies_with_its_actual_parent(tmp_path):
    ready = tmp_path / "worker.json"
    parent_script = r'''
import json, os, subprocess, sys, time
from pathlib import Path
from experiments.finetuning.run_training import process_identity
worker_script = """
import json, os, sys, time
from pathlib import Path
from experiments.finetuning.run_training import guard_parent, process_identity
guard_parent(json.loads(sys.argv[1]))
Path(sys.argv[2]).write_text(json.dumps(process_identity(os.getpid())))
time.sleep(10)
"""
child = subprocess.Popen([sys.executable, '-c', worker_script,
                          json.dumps(process_identity(os.getpid())), sys.argv[1]])
for _ in range(100):
    if Path(sys.argv[1]).exists():
        os._exit(0)
    time.sleep(0.02)
child.kill()
child.wait()
sys.exit(1)
'''
    parent = subprocess.Popen([sys.executable, "-c", parent_script, str(ready)])
    try:
        assert parent.wait(timeout=5) == 0
        owner = json.loads(ready.read_text())
        for _ in range(100):
            if training.owner_is_gone(owner):
                break
            time.sleep(0.02)
        assert training.owner_is_gone(owner)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)


def test_only_owned_worker_can_be_stopped():
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    worker = training.OwnedWorker([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(ValueError, match="owned"):
            worker.stop(other)
        assert other.poll() is None
        worker.stop(worker.process)
        assert worker.process.poll() is not None
        assert other.poll() is None
    finally:
        other.kill()
        other.wait(timeout=5)
        if worker.process.poll() is None:
            worker.stop(worker.process)


def checkpoint(tmp_path, step=100):
    directory = tmp_path / f"checkpoint-{step}"
    directory.mkdir()
    for name in (
        "adapter_model.safetensors",
        "adapter_config.json",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    ):
        (directory / name).write_bytes(b"complete state")
    (directory / "trainer_state.json").write_text(
        json.dumps(
            {
                "global_step": step,
                "max_steps": 200,
                "log_history": [{"loss": 1.0}],
            }
        )
    )
    return directory


def test_partial_checkpoint_is_not_resumable(tmp_path):
    directory = checkpoint(tmp_path)
    (directory / "optimizer.pt").unlink()
    with pytest.raises(ValueError, match="optimizer"):
        training.mark_checkpoint(directory, IDENTITY, 200, save_seconds=2)
    assert not (directory / "complete.json").exists()


def test_checkpoint_hashes_detect_modified_state(tmp_path):
    directory = checkpoint(tmp_path)
    record = training.mark_checkpoint(directory, IDENTITY, 200, save_seconds=2)
    training.validate_resume(record, IDENTITY)
    (directory / "scheduler.pt").write_bytes(b"wrong schedule")
    with pytest.raises(ValueError, match="hash"):
        training.validate_resume(record, IDENTITY)


@pytest.mark.parametrize("field", ["task_id", "model_hash", "data_hash", "recipe_hash"])
def test_resume_rejects_changed_training_identity(tmp_path, field):
    record = training.mark_checkpoint(checkpoint(tmp_path), IDENTITY, 200, save_seconds=2)
    with pytest.raises(ValueError, match="identity"):
        training.validate_resume(record, {**IDENTITY, field: "changed"})


def test_planned_stop_keeps_schedule_and_checkpoint(tmp_path):
    recipe = {"max_steps": 200, "lr_scheduler_type": "cosine", "warmup_ratio": 0.03}
    callback = training.TrainingCallback(
        IDENTITY,
        tmp_path / "status.json",
        deadline=time.monotonic() + 2000,
        max_steps=recipe["max_steps"],
        stop_after_step=100,
    )
    state = SimpleNamespace(global_step=99, max_steps=200)
    control = SimpleNamespace(should_save=False, should_training_stop=False, should_evaluate=True)
    callback.on_step_end(None, state, control)
    assert not control.should_training_stop
    state.global_step = 100
    callback.on_step_end(None, state, control)
    assert control.should_save and control.should_training_stop
    assert not control.should_evaluate
    directory = checkpoint(tmp_path)
    callback.on_save(SimpleNamespace(output_dir=str(tmp_path)), state, control)
    status = json.loads((tmp_path / "status.json").read_text())
    record = training.read_checkpoint(directory, IDENTITY)
    assert record["max_steps"] == 200
    assert record["global_step"] == 100
    assert {"optimizer.pt", "scheduler.pt", "rng_state.pth"} <= record["files"].keys()
    assert status["reason"] == "planned_pause"
    assert recipe == {"max_steps": 200, "lr_scheduler_type": "cosine", "warmup_ratio": 0.03}
    resumed = training.TrainingCallback(
        IDENTITY,
        tmp_path / "resumed.json",
        deadline=time.monotonic() + 2000,
        max_steps=200,
    )
    control.should_training_stop = False
    state.global_step = 101
    resumed.on_step_end(None, state, control)
    assert not control.should_training_stop


def test_save_reserve_uses_slowest_complete_save(tmp_path):
    callback = training.TrainingCallback(
        IDENTITY,
        tmp_path / "status.json",
        deadline=time.monotonic() + 799,
        max_steps=200,
        slowest_save_seconds=400,
    )
    state = SimpleNamespace(global_step=8)
    control = SimpleNamespace(should_save=False, should_training_stop=False)
    callback.on_step_end(None, state, control)
    assert control.should_save and control.should_training_stop
    assert callback.status["reason"] == "budget_reserve"


def test_final_step_forces_complete_save_between_regular_intervals(tmp_path):
    callback = training.TrainingCallback(
        IDENTITY,
        tmp_path / "status.json",
        deadline=time.monotonic() + 2000,
        max_steps=201,
    )
    control = SimpleNamespace(should_save=False, should_training_stop=False)
    callback.on_step_end(None, SimpleNamespace(global_step=201), control)
    assert control.should_save and control.should_training_stop


def test_evaluation_crossing_reserve_does_not_submit_another_step(tmp_path):
    callback = training.TrainingCallback(
        IDENTITY,
        tmp_path / "status.json",
        deadline=time.monotonic() + 599,
        max_steps=200,
    )
    control = SimpleNamespace(should_save=False, should_training_stop=False)
    callback.on_evaluate(None, SimpleNamespace(global_step=20), control)
    assert control.should_save and control.should_training_stop


def test_incomplete_save_preserves_previous_complete_checkpoint(tmp_path):
    callback = training.TrainingCallback(
        IDENTITY,
        tmp_path / "status.json",
        deadline=time.monotonic() + 2000,
        max_steps=200,
    )
    previous = checkpoint(tmp_path, step=50)
    callback.on_save(
        SimpleNamespace(output_dir=str(tmp_path)),
        SimpleNamespace(global_step=50),
        SimpleNamespace(),
    )
    broken = checkpoint(tmp_path, step=100)
    (broken / "rng_state.pth").unlink()
    with pytest.raises(ValueError):
        callback.on_save(
            SimpleNamespace(output_dir=str(tmp_path)),
            SimpleNamespace(global_step=100),
            SimpleNamespace(),
        )
    assert callback.status["last_valid_checkpoint"]["checkpoint_dir"] == str(previous.resolve())


def test_save_hang_retains_previous_complete_marker(tmp_path):
    old = checkpoint(tmp_path, step=50)
    training.mark_checkpoint(old, IDENTITY, 200, save_seconds=2)
    partial = tmp_path / "checkpoint-100"
    partial.mkdir()
    script = (
        "from pathlib import Path; import time; "
        f"Path({str(partial / 'optimizer.pt')!r}).write_bytes(b'partial'); time.sleep(30)"
    )
    worker = training.OwnedWorker([sys.executable, "-c", script])
    assert worker.wait_until(time.monotonic() + 0.3) == "deadline"
    assert training.read_checkpoint(old, IDENTITY)["global_step"] == 50
    assert not (partial / "complete.json").exists()


def test_hash_identity_ignores_output_but_not_data_or_schedule(tmp_path):
    model, data = tmp_path / "model", tmp_path / "data"
    model.mkdir()
    data.mkdir()
    (model / "config.json").write_text("{}")
    (model / "model.safetensors").write_bytes(b"weights")
    (data / "train.json").write_text("[]")
    (data / "dataset_info.json").write_text(json.dumps({"train": {"file_name": "train.json"}}))
    recipe = {
        "model_name_or_path": str(model),
        "dataset_dir": str(data),
        "dataset": "train",
        "max_steps": 200,
        "output_dir": str(tmp_path / "out"),
    }
    first = training.training_identity("todo-019", recipe)
    recipe["output_dir"] = str(tmp_path / "another")
    assert training.training_identity("todo-019", recipe) == first
    recipe["max_steps"] = 100
    assert training.training_identity("todo-019", recipe)["recipe_hash"] != first["recipe_hash"]
    (data / "train.json").write_text('[{"messages": []}]')
    assert training.training_identity("todo-019", recipe)["data_hash"] != first["data_hash"]


def test_initialize_cli_never_loads_training_library(tmp_path):
    repo, path = fake_repository(tmp_path)
    assert (
        training.main(
            ["--task-id", "todo-019", "--budget-file", str(path), "--initialize-budget"], repo=repo
        )
        == 0
    )
    assert json.loads(path.read_text())["occupied_seconds"] == 0
    assert "llamafactory" not in sys.modules


@pytest.mark.parametrize(
    "changes",
    [
        {"save_only_model": True},
        {"save_safetensors": False},
        {"save_total_limit": 1},
        {"save_total_limit": 2, "load_best_model_at_end": True},
        {"resume_from_checkpoint": "old"},
        {"max_steps": 0},
        {"use_ray": True},
        {"dataloader_num_workers": 2},
    ],
)
def test_recipe_rejects_nonresumable_or_unowned_training(changes):
    recipe = {
        "max_steps": 200,
        "output_dir": "run",
        "model_name_or_path": "model",
        "dataset_dir": "data",
        "dataset": "train",
        **changes,
    }
    with pytest.raises(ValueError):
        training.validate_recipe(recipe)


def test_resource_samples_label_scope_and_do_not_invent_missing_gpu(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi unavailable")

    monkeypatch.setattr(subprocess, "run", unavailable)
    sample = training.resource_sample()
    assert sample["gpu_scope"] == "whole device; includes other processes"
    assert sample["gpu"] is None
    assert sample["process_scope"] == "training worker process RSS"


def test_real_cpu_trainer_resume_preserves_schedule_optimizer_rng(tmp_path):
    pytest.importorskip(
        "accelerate", reason="Real Trainer integration uses the separate training venv"
    )
    # Real framework integration without Factory, GPU, downloads, or production training.
    script = r"""
import json, random, sys
from pathlib import Path
import numpy as np
import torch
from transformers import Trainer, TrainerCallback, TrainingArguments, set_seed
from experiments.finetuning.run_training import TrainingCallback, read_checkpoint
torch.set_num_threads(1)
root = Path(sys.argv[1])
identity = {"task_id":"todo-019", "model_hash":"a"*64,
            "data_hash":"b"*64, "recipe_hash":"c"*64}
class Callback(TrainingCallback, TrainerCallback):
    pass
class Model(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(2, 1)
    def forward(self, input_ids, labels):
        value = self.linear(torch.nn.functional.dropout(input_ids.float(), p=0.2,
                                                        training=self.training)).squeeze(-1)
        return {"loss": ((value-labels)**2).mean(), "logits": value}
data = [{"input_ids": torch.tensor([1., 2.]), "labels": torch.tensor(1.)}] * 8
def run(name, stop=None, resume=None):
    import time
    set_seed(42)
    model = Model()
    args = TrainingArguments(output_dir=str(root/name), max_steps=200,
        per_device_train_batch_size=2, learning_rate=0.001, lr_scheduler_type="cosine",
        warmup_ratio=0.03, save_strategy="steps", save_steps=200, report_to=[],
        disable_tqdm=True, use_cpu=True, logging_steps=100, seed=42,
        dataloader_pin_memory=False)
    callback = Callback(identity, root/(name+".json"), deadline=time.monotonic()+3600,
                        max_steps=200, stop_after_step=stop)
    trainer = Trainer(model=model,args=args,train_dataset=data,callbacks=[callback])
    trainer.train(resume_from_checkpoint=resume)
    return model, trainer
partial, first = run("partial", stop=100)
cp = root/"partial/checkpoint-100"
record = read_checkpoint(cp, identity)
assert record["max_steps"] == 200 and record["global_step"] == 100
opt = torch.load(cp/"optimizer.pt", weights_only=True)
schedule = torch.load(cp/"scheduler.pt", weights_only=True)
rng = torch.load(cp/"rng_state.pth", weights_only=False)
assert schedule["last_epoch"] == 100
assert all(float(state["step"]) == 100 for state in opt["state"].values())
assert {"python", "numpy", "cpu"} <= rng.keys()
resumed, second = run("resumed", resume=str(cp))
whole, full = run("whole")
assert second.state.global_step == 200
for key, value in whole.state_dict().items():
    torch.testing.assert_close(resumed.state_dict()[key], value, rtol=0, atol=0)
assert second.lr_scheduler.state_dict() == full.lr_scheduler.state_dict()
print("REAL_CPU_RESUME_OK")
"""
    import os

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        timeout=90,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_CPU_RESUME_OK" in result.stdout
