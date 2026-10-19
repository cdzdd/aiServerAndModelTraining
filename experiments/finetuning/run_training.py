"""Bounded, resumable local training; GPU libraries are imported only by the worker."""

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

BUDGET_SECONDS = 86400


class BudgetDeadlineExceeded(ValueError):
    pass


def remaining_seconds(
    used_seconds: float, elapsed_seconds: float, budget_seconds: int = BUDGET_SECONDS
) -> float:
    return max(0.0, budget_seconds - used_seconds - elapsed_seconds)


def atomic_json(path, record):
    path = Path(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Unreadable JSON: {path}") from error


def native_path(value):
    text = str(value).replace("\\", "/")
    if os.name != "nt" and re.match(r"^[A-Za-z]:/", text):
        text = f"/mnt/{text[0].lower()}/{text[3:]}"
    return Path(text)


def git_common_directory(repo):
    dotgit = Path(repo).resolve() / ".git"
    if dotgit.is_file():
        pointer = dotgit.read_text(encoding="utf-8").strip()
        if not pointer.startswith("gitdir: "):
            raise ValueError("Invalid Git worktree pointer")
        gitdir = native_path(pointer[8:])
        if not gitdir.is_absolute():
            gitdir = dotgit.parent / gitdir
    else:
        gitdir = dotgit
    common = gitdir / "commondir"
    if common.is_file():
        target = native_path(common.read_text(encoding="utf-8").strip())
        gitdir = target if target.is_absolute() else gitdir / target
    if not gitdir.is_dir():
        raise ValueError("Cannot resolve real Git common directory")
    return gitdir.resolve()


def resolve_budget_file(task_id, supplied, budget_seconds, repo):
    if task_id not in {"todo-019", "todo-020"}:
        raise ValueError("Only claimed training tasks todo-019/todo-020 are supported")
    if budget_seconds != BUDGET_SECONDS:
        raise ValueError("The task budget must remain 86400 seconds")
    coordination = git_common_directory(repo) / "codex-coordination"
    canonical = (coordination / "training-budgets" / f"{task_id}.json").resolve()
    claim = read_json(coordination / "claims" / f"{task_id}.json")
    if (
        claim.get("task_id") != task_id
        or claim.get("training_budget_seconds") != BUDGET_SECONDS
        or native_path(claim.get("training_budget_path", "")).resolve() != canonical
        or native_path(supplied).resolve() != canonical
    ):
        raise ValueError("Budget path/claim must match the canonical Git common directory")
    return canonical


def initialize_budget(path, task_id):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = path.with_suffix(".initialized")
    if path.exists() or marker.exists():
        raise ValueError("Budget already initialized; never replace or reset it")
    # This tombstone survives accidental ledger deletion. Interrupted initialization blocks safely.
    with marker.open("x", encoding="utf-8") as stream:
        stream.write(task_id)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_json(
        path,
        {
            "schema": 1,
            "task_id": task_id,
            "budget_seconds": BUDGET_SECONDS,
            "occupied_seconds": 0.0,
            "attempts": [],
            "last_valid_checkpoint": None,
            "slowest_save_seconds": 0.0,
        },
    )


def process_identity(pid):
    """PID plus kernel birth identity, never PID alone. None means confirmed absent."""
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return None
            raise ValueError("Cannot verify process owner")
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                raise ValueError("Cannot verify process owner exit status")
            if exit_code.value != 259:  # A terminated process may still have an open OS handle.
                return None
            values = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(v) for v in values]):
                raise ValueError("Cannot verify process owner birth time")
            birth = str((values[0].dwHighDateTime << 32) + values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    else:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ValueError("Cannot verify process owner") from error
        fields = stat.rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        birth = boot + ":" + fields[19]
    return {"pid": pid, "birth": birth, "host": platform.node(), "platform": os.name}


def owner_is_gone(owner):
    if (
        not isinstance(owner, dict)
        or owner.get("host") != platform.node()
        or owner.get("platform") != os.name
        or not isinstance(owner.get("pid"), int)
        or not owner.get("birth")
    ):
        raise ValueError("Cannot verify previous process owner")
    return process_identity(owner["pid"]) != owner


def nonnegative(value):
    return (
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


class BudgetLedger:
    def __init__(self, path, task_id, *, clock=time):
        self.path, self.task_id, self.clock = Path(path), task_id, clock
        self.lock = None
        self.record = None
        self.last_mono = None

    def __enter__(self):
        self.lock = self.path.with_suffix(".lock").open("a+b")
        if os.fstat(self.lock.fileno()).st_size == 0:
            self.lock.write(b"0")
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.lock.close()
            raise ValueError("Another budget writer is active") from error
        try:
            self.record = read_json(self.path)
            self._validate()
            self._recover()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.lock:
            if os.name == "nt":
                import msvcrt

                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.lock.close()
            self.lock = None

    def _validate(self):
        record = self.record

        def require(condition):
            if not condition:
                raise ValueError("Corrupt or mismatched budget ledger")

        try:
            require(self.path.with_suffix(".initialized").read_text() == self.task_id)
            require(record["schema"] == 1 and record["task_id"] == self.task_id)
            require(record["budget_seconds"] == BUDGET_SECONDS)
            require(nonnegative(record["occupied_seconds"]))
            require(nonnegative(record["slowest_save_seconds"]))
            require(isinstance(record["attempts"], list))
            total = 0.0
            for index, attempt in enumerate(record["attempts"]):
                require(nonnegative(attempt["occupied_seconds"]))
                require(nonnegative(attempt["last_utc"]))
                require(nonnegative(attempt["started_utc"]))
                require(attempt["last_utc"] >= attempt["started_utc"])
                require(attempt["phase"] in {"preflight", "formal"})
                require(attempt["identity"]["task_id"] == self.task_id)
                require(isinstance(attempt["parent"], dict))
                require(attempt["reason"] is not None or index == len(record["attempts"]) - 1)
                require(
                    math.isclose(
                        attempt["allowance_seconds"],
                        remaining_seconds(total, 0),
                        rel_tol=0,
                        abs_tol=1e-6,
                    )
                )
                for clock_name in ("utc", "monotonic"):
                    require(
                        math.isclose(
                            attempt[f"deadline_{clock_name}"],
                            attempt[f"started_{clock_name}"] + attempt["allowance_seconds"],
                            rel_tol=0,
                            abs_tol=1e-6,
                        )
                    )
                total += attempt["occupied_seconds"]
            require(math.isclose(total, record["occupied_seconds"], abs_tol=1e-6))
        except (KeyError, TypeError, OSError) as error:
            raise ValueError(
                "Corrupt or mismatched budget ledger; manual investigation required"
            ) from error

    @property
    def active(self):
        if self.record["attempts"] and self.record["attempts"][-1]["reason"] is None:
            return self.record["attempts"][-1]
        return None

    @property
    def remaining(self):
        return remaining_seconds(self.record["occupied_seconds"], 0)

    def save(self):
        atomic_json(self.path, self.record)

    def _recover(self):
        attempt = self.active
        if attempt is None:
            return
        now = self.clock.time()
        if now < attempt["last_utc"]:
            raise ValueError("UTC clock moved backwards; refusing automatic recovery")
        for owner in (attempt["parent"], attempt.get("worker")):
            if owner is not None and not owner_is_gone(owner):
                raise ValueError("Previous process owner is still alive; refusing recovery")
        delta = now - attempt["last_utc"]
        attempt["occupied_seconds"] += delta
        self.record["occupied_seconds"] += delta
        attempt.update(last_utc=now, reason="recovered_crash")
        self.save()

    def start(self, identity, phase):
        if self.active:
            raise ValueError("An attempt is already active")
        if self.remaining <= 0:
            raise ValueError("Training budget exhausted")
        if identity["task_id"] != self.task_id or phase not in {"preflight", "formal"}:
            raise ValueError("Attempt task/phase mismatch")
        now = self.clock.time()
        if self.record["attempts"] and now < self.record["attempts"][-1]["last_utc"]:
            raise ValueError("UTC clock moved backwards")
        self.last_mono = self.clock.monotonic()
        allowance = self.remaining
        self.record["attempts"].append(
            {
                "identity": identity,
                "phase": phase,
                "parent": process_identity(os.getpid()),
                "worker": None,
                "started_utc": now,
                "last_utc": now,
                "started_monotonic": self.last_mono,
                "last_monotonic": self.last_mono,
                "allowance_seconds": allowance,
                "deadline_monotonic": self.last_mono + allowance,
                "deadline_utc": now + allowance,
                "occupied_seconds": 0.0,
                "reason": None,
            }
        )
        self.save()

    def heartbeat(self, *, on_exhausted=None):
        attempt = self.active
        if attempt is None or self.last_mono is None:
            raise ValueError("No active owned attempt")
        now, mono = self.clock.time(), self.clock.monotonic()
        if now < attempt["last_utc"] or mono < self.last_mono:
            raise ValueError("Accounting clock moved backwards")
        # BOOTTIME/suspend and forward UTC adjustments must never grant extra occupied time.
        delta = max(mono - self.last_mono, now - attempt["last_utc"])
        attempt["occupied_seconds"] += delta
        self.record["occupied_seconds"] += delta
        attempt.update(last_utc=now, last_monotonic=mono)
        self.last_mono = mono
        if self.remaining <= 0 and on_exhausted is not None:
            on_exhausted()  # Terminate before any possibly blocking ledger persistence.
        self.save()

    def finish(self, reason):
        worker = self.active.get("worker") if self.active else None
        if worker and not owner_is_gone(worker):
            raise ValueError("Cannot stop accounting before worker exits and releases GPU")
        self.heartbeat()
        self.active["reason"] = reason
        self.save()


class OwnedWorker:
    """Retains the actual Popen handle. Arbitrary PIDs can never be terminated here."""

    def __init__(self, command, *, deadline, utc_deadline, **kwargs):
        if deadline <= time.monotonic() or utc_deadline <= time.time():
            raise BudgetDeadlineExceeded("Worker deadline has already expired")
        self.deadline, self.utc_deadline = deadline, utc_deadline
        self.expired = threading.Event()
        self.cancel_deadline = threading.Event()
        self.process = subprocess.Popen(command, **kwargs)
        self._arm()

    def _arm(self):
        def kill_at_deadline():
            while not self.cancel_deadline.is_set():
                remaining = min(self.deadline - time.monotonic(), self.utc_deadline - time.time())
                if remaining <= 0:
                    self.expire()
                    return
                self.cancel_deadline.wait(min(0.1, remaining))

        self.timer = threading.Thread(target=kill_at_deadline, daemon=True)
        self.timer.start()

    def expire(self):
        if self.process.poll() is None:
            self.expired.set()
            try:
                self.process.kill()
            except ProcessLookupError:
                pass  # It exited between poll and kill.

    def stop(self, process):
        if process is not self.process:
            raise ValueError("Can stop only the owned worker Popen handle")
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        self.cancel_deadline.set()

    def wait_until(self, heartbeat=None):
        next_heartbeat = time.monotonic()
        try:
            while self.process.poll() is None:
                now = time.monotonic()
                if heartbeat and now >= next_heartbeat:
                    heartbeat()
                    next_heartbeat = now + 10
                time.sleep(min(0.05, max(0.001, self.deadline - now)))
            return (
                "deadline"
                if self.expired.is_set()
                else ("completed" if self.process.returncode == 0 else "worker_failed")
            )
        except BaseException:
            self.stop(self.process)
            raise
        finally:
            self.cancel_deadline.set()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def training_identity(task_id, recipe):
    if task_id == "todo-020" and recipe.get("finetuning_type") != "full":
        raise ValueError("todo-020 requires full training from its original base")
    model = Path(recipe["model_name_or_path"]).resolve()
    if not model.is_dir():
        raise ValueError("model_name_or_path must be a frozen local model directory")
    model_files = {
        str(path.relative_to(model)): file_hash(path)
        for path in sorted(model.rglob("*"))
        if path.is_file() and ".cache" not in path.relative_to(model).parts
    }
    if not model_files:
        raise ValueError("Frozen model directory is empty")
    data = Path(recipe["dataset_dir"]).resolve()
    info = read_json(data / "dataset_info.json")
    data_files, selections = {}, {}
    for kind in ("dataset", "eval_dataset"):
        names = recipe.get(kind, [])
        if isinstance(names, str):
            names = [name.strip() for name in names.split(",") if name.strip()]
        for name in names:
            entry = info[name]
            if not entry.get("file_name"):
                raise ValueError("Training datasets must be frozen local files")
            path = (data / entry["file_name"]).resolve()
            if not path.is_relative_to(data):
                raise ValueError("Dataset escapes its frozen dataset directory")
            data_files[entry["file_name"]] = file_hash(path)
            selections[name] = entry
    if not data_files:
        raise ValueError("No local training dataset selected")
    # Output/operational resume flags never alter recipe identity or the canonical task budget.
    normalized = {
        key: value
        for key, value in recipe.items()
        if key
        not in {
            "output_dir",
            "logging_dir",
            "overwrite_output_dir",
            "resume_from_checkpoint",
            "model_name_or_path",
            "dataset_dir",
        }
    }
    return {
        "task_id": task_id,
        "model_hash": json_hash(model_files),
        "data_hash": json_hash({"files": data_files, "selections": selections}),
        "recipe_hash": json_hash(normalized),
    }


def checkpoint_files(directory, task_id=None, *, verify_formats=True):
    directory = Path(directory)
    required = ["optimizer.pt", "scheduler.pt", "rng_state.pth", "trainer_state.json"]
    adapter = (directory / "adapter_model.safetensors").is_file()
    single = (directory / "model.safetensors").is_file()
    indexed = (directory / "model.safetensors.index.json").is_file()
    weight_map = None
    if adapter:
        if task_id == "todo-020" or single or indexed:
            raise ValueError("Full checkpoint cannot contain adapter weights")
        required += ["adapter_model.safetensors", "adapter_config.json"]
    elif single and indexed:
        raise ValueError("Ambiguous full checkpoint weights/index")
    elif single:
        required += ["model.safetensors"]
    elif indexed:
        index = read_json(directory / "model.safetensors.index.json")
        weight_map = index.get("weight_map") if isinstance(index, dict) else None
        if (
            not isinstance(weight_map, dict)
            or not weight_map
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value.endswith(".safetensors")
                for key, value in weight_map.items()
            )
        ):
            raise ValueError("Invalid full checkpoint weight_map index")
        required += ["model.safetensors.index.json", *sorted(set(weight_map.values()))]
    else:
        raise ValueError("Checkpoint has no complete safetensors weights")
    if not adapter:
        extra_templates = directory / "additional_chat_templates"
        if extra_templates.exists() or extra_templates.is_symlink():
            raise ValueError("Full checkpoint does not support additional_chat_templates")
        if any(
            (directory / name).exists()
            for name in (
                "adapter_config.json",
                "adapter_model.bin",
                "pytorch_model.bin",
                "pytorch_model.bin.index.json",
            )
        ):
            raise ValueError("Full checkpoint cannot contain adapter or alternate weights")
        # The frozen Qwen fast tokenizer saves its actual template outside tokenizer_config.
        required += [
            "config.json",
            "tokenizer_config.json",
            "tokenizer.json",
            "chat_template.jinja",
        ]
        required += [
            name
            for name in (
                "generation_config.json",
                "special_tokens_map.json",
                "added_tokens.json",
                "vocab.json",
                "merges.txt",
                "training_args.bin",
            )
            if (directory / name).exists()
        ]
    for name in required:
        path = (directory / name).resolve()
        if (
            "/" in name
            or "\\" in name
            or not path.is_relative_to(directory.resolve())
            or (directory / name).is_symlink()
            or not path.is_file()
            or path.stat().st_size == 0
        ):
            raise ValueError(f"Incomplete checkpoint: {name}")
    if not adapter and verify_formats:
        validate_full_checkpoint_formats(directory, weight_map)
    return required


def validate_full_checkpoint_formats(directory, weight_map):
    from safetensors import safe_open
    from tokenizers import Tokenizer

    config = read_json(directory / "config.json")
    tokenizer_config = read_json(directory / "tokenizer_config.json")
    if not isinstance(config, dict) or not config.get("model_type"):
        raise ValueError("Invalid full checkpoint config.json")
    if not isinstance(tokenizer_config, dict) or not tokenizer_config.get("tokenizer_class"):
        raise ValueError("Invalid full checkpoint tokenizer_config.json")
    if not (directory / "chat_template.jinja").read_text(encoding="utf-8").strip():
        raise ValueError("Invalid full checkpoint chat_template.jinja")
    try:
        Tokenizer.from_file(str(directory / "tokenizer.json"))
        shards = set(weight_map.values()) if weight_map else {"model.safetensors"}
        for name in shards:
            # Read headers only: never instantiate the model or copy its tensors here.
            with safe_open(str(directory / name), framework="numpy") as stream:
                keys = set(stream.keys())
            expected = (
                {key for key, shard in weight_map.items() if shard == name} if weight_map else keys
            )
            if not keys or keys != expected:
                raise ValueError(f"Full checkpoint shard membership mismatch: {name}")
    except Exception as error:
        raise ValueError(f"Invalid full checkpoint tokenizer/weights format: {error}") from error


def mark_checkpoint(directory, identity, max_steps, *, save_seconds):
    directory = Path(directory).resolve()
    names = checkpoint_files(directory, identity["task_id"])
    state = read_json(directory / "trainer_state.json")
    step = state.get("global_step")
    if (
        not isinstance(step, int)
        or step <= 0
        or step > max_steps
        or state.get("max_steps") != max_steps
        or directory.name != f"checkpoint-{step}"
    ):
        raise ValueError("Checkpoint trainer state/schedule mismatch")
    for log in state.get("log_history", []):
        if any(isinstance(value, float) and not math.isfinite(value) for value in log.values()):
            raise ValueError("Checkpoint contains non-finite trainer metrics")
    record = {
        "schema": 1,
        "identity": identity,
        "checkpoint_dir": str(directory),
        "global_step": step,
        "max_steps": max_steps,
        "save_seconds": save_seconds,
        "files": {name: file_hash(directory / name) for name in names},
    }
    atomic_json(directory / "complete.json", record)
    return record


def validate_resume(record: dict, current: dict) -> None:
    if record.get("schema") != 1 or any(
        record.get("identity", {}).get(key) != current.get(key)
        for key in ("task_id", "model_hash", "data_hash", "recipe_hash")
    ):
        raise ValueError("Resume training identity mismatch")
    directory = Path(record["checkpoint_dir"])
    names = checkpoint_files(directory, current["task_id"], verify_formats=False)
    if set(names) != set(record.get("files", {})):
        raise ValueError("Incomplete checkpoint hash manifest")
    for name in names:
        if file_hash(directory / name) != record["files"][name]:
            raise ValueError(f"Checkpoint hash mismatch: {name}")
    state = read_json(directory / "trainer_state.json")
    if state.get("global_step") != record.get("global_step") or state.get(
        "max_steps"
    ) != record.get("max_steps"):
        raise ValueError("Checkpoint trainer state mismatch")


def read_checkpoint(directory, identity):
    directory = Path(directory).resolve()
    record = read_json(directory / "complete.json")
    if Path(record["checkpoint_dir"]).resolve() != directory:
        raise ValueError("Checkpoint marker refers to another directory")
    validate_resume(record, identity)
    return record


class TrainingCallback:
    """TrainerCallback mixin: import the framework only inside the GPU worker."""

    def __init__(
        self,
        identity,
        status_file,
        *,
        deadline,
        max_steps,
        utc_deadline=None,
        stop_after_step=None,
        slowest_save_seconds=0,
    ):
        self.identity, self.status_file = identity, Path(status_file)
        self.deadline, self.max_steps = deadline, max_steps
        self.utc_deadline = utc_deadline
        self.stop_after_step = stop_after_step
        self.slowest_save_seconds = slowest_save_seconds
        self.save_started = None
        self.started = time.monotonic()
        self.status = {
            "reason": "running",
            "last_valid_checkpoint": None,
            "slowest_save_seconds": slowest_save_seconds,
            "steps": 0,
            "input_tokens": 0,
            "target_tokens": 0,
            "token_scope": "training forwards only; attention_mask and labels != -100",
        }
        self.hook = None

    def on_train_begin(self, args, state, control, model=None, **kwargs):
        if self.remaining <= self.reserve_seconds:
            self.status["reason"] = "budget_reserve_before_training"
            self.publish()
            raise ValueError("Insufficient budget after model loading to start training")
        self.started = time.monotonic()

        def count_tokens(module, positional, inputs):
            if module.training:
                mask, labels = inputs.get("attention_mask"), inputs.get("labels")
                if mask is not None:
                    self.status["input_tokens"] += int(mask.sum().item())
                elif inputs.get("input_ids") is not None:
                    self.status["input_tokens"] += inputs["input_ids"].numel()
                if labels is not None:
                    self.status["target_tokens"] += int((labels != -100).sum().item())

        if model is not None:
            self.hook = model.register_forward_pre_hook(count_tokens, with_kwargs=True)
        self.publish()
        return control

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = logs or {}
        for key in ("loss", "eval_loss", "learning_rate", "grad_norm"):
            if key in logs:
                value = float(logs[key])
                if not math.isfinite(value):
                    raise ValueError(f"Non-finite training metric: {key}")
                self.status[key] = value
        self.publish()
        return control

    def on_train_end(self, args, state, control, **kwargs):
        if self.hook is not None:
            self.hook.remove()
        if self.status["reason"] == "running":
            self.status["reason"] = (
                "early_stopping"
                if control.should_training_stop and state.global_step < self.max_steps
                else "completed"
            )
        self.publish()
        return control

    @property
    def reserve_seconds(self):
        return max(600, 2 * self.slowest_save_seconds)

    @property
    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if self.utc_deadline is not None:
            remaining = min(remaining, self.utc_deadline - time.time())
        return remaining

    def publish(self):
        self.status["training_elapsed_seconds"] = time.monotonic() - self.started
        self.status["input_tokens_per_second"] = self.status["input_tokens"] / max(
            0.001, self.status["training_elapsed_seconds"]
        )
        atomic_json(self.status_file, self.status)

    def on_step_end(self, args, state, control, **kwargs):
        self.status["steps"] = state.global_step
        if self.stop_after_step is not None and state.global_step >= self.stop_after_step:
            self.status["reason"] = "planned_pause"
        elif self.remaining <= self.reserve_seconds:
            self.status["reason"] = "budget_reserve"
        if self.status["reason"] in {"planned_pause", "budget_reserve"}:
            control.should_training_stop = control.should_save = True
            control.should_evaluate = False
        if state.global_step >= self.max_steps:
            control.should_training_stop = control.should_save = True
        # Saving is synchronous after this callback. Include intervening validation conservatively.
        self.save_started = time.monotonic()
        return control

    def on_evaluate(self, args, state, control, **kwargs):
        if self.remaining <= self.reserve_seconds:
            self.status["reason"] = "budget_reserve"
            control.should_training_stop = control.should_save = True
        return control

    def on_save(self, args, state, control, **kwargs):
        directory = Path(args.output_dir) / f"checkpoint-{state.global_step}"
        started = self.save_started or time.monotonic()
        record = mark_checkpoint(
            directory,
            self.identity,
            self.max_steps,
            save_seconds=time.monotonic() - started,
        )
        # Hashing is part of the complete save duration, and thus part of the future reserve.
        duration = time.monotonic() - started
        record["save_seconds"] = duration
        atomic_json(directory / "complete.json", record)
        self.slowest_save_seconds = max(self.slowest_save_seconds, duration)
        self.status.update(
            last_valid_checkpoint=record, slowest_save_seconds=self.slowest_save_seconds
        )
        self.publish()
        if self.remaining <= self.reserve_seconds:
            control.should_training_stop = True
            self.status["reason"] = "budget_reserve"
            self.publish()
        return control


def validate_recipe(recipe):
    if recipe.get("finetuning_type") == "full":
        from experiments.finetuning.audit_full_model import validate_full_recipe

        validate_full_recipe(recipe)
    if "tokenized_path" in recipe:
        raise ValueError("tokenized_path is unsupported; load the hashed raw train/dev files")
    if not isinstance(recipe.get("max_steps"), int) or recipe["max_steps"] <= 0:
        raise ValueError("Recipe requires positive fixed max_steps")
    retained = 3 if recipe.get("load_best_model_at_end") else 2
    if (
        recipe.get("save_only_model", False)
        or not recipe.get("save_safetensors", True)
        or recipe.get("save_strategy", "steps") != "steps"
        or (recipe.get("save_total_limit") is not None and recipe["save_total_limit"] < retained)
    ):
        raise ValueError(
            f"Require full step checkpoints and at least {retained} retained checkpoints"
        )
    if recipe.get("resume_from_checkpoint") or recipe.get("adapter_name_or_path"):
        raise ValueError("Use --resume with a complete checkpoint; fresh runs start from base")
    if (
        recipe.get("use_ray")
        or recipe.get("deepspeed")
        or recipe.get("fsdp")
        or recipe.get("dataloader_num_workers", 0) != 0
        or recipe.get("preprocessing_num_workers", 1) != 1
        or int(os.environ.get("WORLD_SIZE", "1")) != 1
    ):
        raise ValueError("Only a single owned training process is supported")
    if recipe.get("push_to_hub"):
        raise ValueError("This local training CLI does not publish to the Hub")


def resource_sample():
    sample = {
        "utc": time.time(),
        "gpu_scope": "whole device; includes other processes",
        "gpu": None,
        "process_scope": "training worker process RSS",
        "process_rss_bytes": None,
        "pid": os.getpid(),
    }
    if os.name != "nt":
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    sample["process_rss_bytes"] = int(line.split()[1]) * 1024
        except OSError:
            pass
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.used,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        sample["gpu"] = []
        for line in result.stdout.strip().splitlines():
            values = line.split(",")
            fields = ("index", "memory_used_mib", "temperature_c", "power_w")
            row = {}
            for field, value in zip(fields, values, strict=True):
                try:
                    row[field] = float(value.strip())
                except ValueError:
                    row[field] = None
            sample["gpu"].append(row)
    except (OSError, subprocess.SubprocessError, ValueError):
        sample["gpu"] = None
    return sample


def guard_parent(parent):
    if os.name != "posix" or not Path("/proc").is_dir():
        raise ValueError("Actual training runs require Linux/WSL")
    # Linux clears PDEATHSIG after fork; set in this worker, then close the parent-exit race.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, 9, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG, SIGKILL
        raise ValueError("Cannot install parent-death protection")
    if os.getppid() != parent["pid"] or process_identity(os.getppid()) != parent:
        raise ValueError("Training worker parent identity changed")


def factory_training_arguments(recipe, phase, budget_callback):
    effective_recipe = dict(recipe)
    # Factory would otherwise append a second callback using its default threshold of zero.
    effective_recipe.pop("early_stopping_steps", None)
    callbacks = [budget_callback]
    if recipe.get("finetuning_type") == "full":
        from experiments.finetuning.audit_full_model import FullModelAuditCallback
        from transformers import TrainerCallback

        class FullAudit(FullModelAuditCallback, TrainerCallback):
            pass

        callbacks.append(FullAudit())
    if phase == "formal":
        from transformers import EarlyStoppingCallback

        callbacks.insert(
            0,
            EarlyStoppingCallback(early_stopping_patience=3, early_stopping_threshold=0.001),
        )
    return effective_recipe, callbacks


def worker_main(spec_path):
    spec = read_json(spec_path)
    guard_parent(spec["parent"])
    ledger = read_json(spec["budget_file"])
    if ledger["attempts"][-1]["parent"] != spec["parent"]:
        raise ValueError("Worker does not belong to active budget attempt")
    # These imports and all model loading occur after the budget attempt starts.
    import torch
    from llamafactory.train.tuner import run_exp
    from transformers import TrainerCallback

    class Callback(TrainingCallback, TrainerCallback):
        pass

    callback = Callback(
        spec["identity"],
        spec["status_file"],
        deadline=spec["deadline"],
        utc_deadline=spec["utc_deadline"],
        max_steps=spec["recipe"]["max_steps"],
        stop_after_step=spec["stop_after_step"],
        slowest_save_seconds=spec["slowest_save_seconds"],
    )
    stopped = threading.Event()

    def sample_resources():
        with Path(spec["resources_file"]).open("a", encoding="utf-8") as stream:
            while not stopped.is_set():
                sampled_at = time.monotonic()
                sample = resource_sample()
                sample.update(
                    input_tokens=callback.status["input_tokens"],
                    target_tokens=callback.status["target_tokens"],
                    steps=callback.status["steps"],
                    cuda_scope="training worker PyTorch allocator peaks",
                    cuda_allocated_peak_bytes=None,
                    cuda_reserved_peak_bytes=None,
                )
                if torch.cuda.is_initialized():
                    sample["cuda_allocated_peak_bytes"] = torch.cuda.max_memory_allocated()
                    sample["cuda_reserved_peak_bytes"] = torch.cuda.max_memory_reserved()
                stream.write(json.dumps(sample, allow_nan=False) + "\n")
                stream.flush()
                stopped.wait(max(0, 10 - (time.monotonic() - sampled_at)))

    sampler = threading.Thread(target=sample_resources, daemon=True)
    sampler.start()
    try:
        effective_recipe, callbacks = factory_training_arguments(
            spec["recipe"], spec["phase"], callback
        )
        run_exp(effective_recipe, callbacks=callbacks)
        checkpoint = callback.status["last_valid_checkpoint"]
        if checkpoint is None or checkpoint["global_step"] != callback.status["steps"]:
            raise ValueError("Training ended without a complete final checkpoint")
        return 0
    except BaseException as error:
        callback.status["reason"] = (
            "oom" if isinstance(error, torch.OutOfMemoryError) else "worker_failed"
        )
        callback.status["error_type"] = type(error).__name__
        callback.publish()
        raise
    finally:
        stopped.set()
        sampler.join(timeout=3)
        # Always retain end-of-attempt allocator peaks, including very short attempts.
        final = resource_sample()
        final.update(
            final=True,
            steps=callback.status["steps"],
            input_tokens=callback.status["input_tokens"],
            target_tokens=callback.status["target_tokens"],
            cuda_scope="training worker PyTorch allocator peaks",
            cuda_allocated_peak_bytes=(
                torch.cuda.max_memory_allocated() if torch.cuda.is_initialized() else None
            ),
            cuda_reserved_peak_bytes=(
                torch.cuda.max_memory_reserved() if torch.cuda.is_initialized() else None
            ),
        )
        with Path(spec["resources_file"]).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(final, allow_nan=False) + "\n")


def main(argv=None, *, repo=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True, choices=["todo-019", "todo-020"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--budget-file", required=True)
    parser.add_argument("--budget-seconds", type=int, default=BUDGET_SECONDS)
    parser.add_argument("--phase", choices=["preflight", "formal"])
    parser.add_argument("--stop-after-step", type=int)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--initialize-budget", action="store_true")
    options = parser.parse_args(argv)
    repo = Path(repo) if repo else Path(__file__).resolve().parents[2]
    path = resolve_budget_file(options.task_id, options.budget_file, options.budget_seconds, repo)
    if options.initialize_budget:
        initialize_budget(path, options.task_id)
        print(f"Initialized {path}; 0 seconds consumed, limit {BUDGET_SECONDS}")
        return 0
    if options.config is None or options.phase is None:
        parser.error("--config and --phase are required for training")
    if os.name != "posix":
        raise ValueError("Use the isolated Linux/WSL training environment")
    import yaml

    recipe = yaml.safe_load(options.config.read_text(encoding="utf-8"))
    validate_recipe(recipe)
    if (
        options.stop_after_step is not None
        and not 0 < options.stop_after_step <= recipe["max_steps"]
    ):
        raise ValueError("stop-after-step must be within the fixed recipe schedule")
    # File hashing is preparation. No model is instantiated here.
    identity = training_identity(options.task_id, recipe)
    identity["code_hash"] = file_hash(__file__)
    identity["config_file_hash"] = file_hash(options.config)
    resumed = read_checkpoint(options.resume, identity) if options.resume else None
    if (
        resumed
        and options.stop_after_step is not None
        and options.stop_after_step <= resumed["global_step"]
    ):
        raise ValueError("stop-after-step must be after the resumed checkpoint step")
    output = Path(recipe["output_dir"]).resolve()
    if not resumed and output.exists() and any(output.iterdir()):
        raise ValueError("Fresh training requires an empty output directory")
    if resumed:
        recipe["resume_from_checkpoint"] = str(options.resume.resolve())
    with BudgetLedger(path, options.task_id) as ledger:
        ledger.start(identity, options.phase)
        deadline = ledger.active["deadline_monotonic"]
        utc_deadline = ledger.active["deadline_utc"]
        attempt_id = len(ledger.record["attempts"])
        prefix = path.parent / f"{options.task_id}-attempt-{attempt_id}"
        status_file = prefix.with_suffix(".status.json")
        spec_path = prefix.with_suffix(".worker.json")
        spec = {
            "identity": identity,
            "phase": options.phase,
            "recipe": recipe,
            "parent": ledger.active["parent"],
            "budget_file": str(path),
            "deadline": deadline,
            "utc_deadline": utc_deadline,
            "status_file": str(status_file),
            "resources_file": str(prefix.with_suffix(".resources.jsonl")),
            "stop_after_step": options.stop_after_step,
            "slowest_save_seconds": ledger.record["slowest_save_seconds"],
        }
        worker = None

        def heartbeat():
            if status_file.exists():
                status = read_json(status_file)
                if status.get("last_valid_checkpoint"):
                    ledger.record["last_valid_checkpoint"] = status["last_valid_checkpoint"]
                ledger.record["slowest_save_seconds"] = max(
                    ledger.record["slowest_save_seconds"],
                    status.get("slowest_save_seconds", 0),
                )
            ledger.heartbeat(on_exhausted=worker.expire)

        try:
            atomic_json(spec_path, spec)
            with prefix.with_suffix(".log").open("ab", buffering=0) as log:
                worker = OwnedWorker(
                    [sys.executable, str(Path(__file__).resolve()), "--worker", str(spec_path)],
                    stdout=log,
                    stderr=log,
                    deadline=deadline,
                    utc_deadline=utc_deadline,
                )
                ledger.active["worker"] = process_identity(worker.process.pid)
                ledger.save()
                reason = worker.wait_until(heartbeat)
            heartbeat()
            if reason == "completed":
                status = read_json(status_file)
                reason = status["reason"]
            elif reason == "worker_failed" and status_file.exists():
                status = read_json(status_file)
                reason = "oom" if status.get("reason") == "oom" else "worker_failed"
            ledger.finish(reason)
            print(
                json.dumps(
                    {
                        "reason": reason,
                        "occupied_seconds": ledger.record["occupied_seconds"],
                        "remaining_seconds": ledger.remaining,
                        "log": str(prefix.with_suffix(".log")),
                        "last_valid_checkpoint": ledger.record["last_valid_checkpoint"],
                    }
                )
            )
            return (
                0
                if reason in {"completed", "early_stopping", "planned_pause", "budget_reserve"}
                else 1
            )
        except BaseException as error:
            if worker and worker.process.poll() is None:
                worker.stop(worker.process)
            # If clock/storage fails, leave the attempt open for conservative crash recovery.
            ledger.finish(
                "deadline" if isinstance(error, BudgetDeadlineExceeded) else "interrupted_or_failed"
            )
            raise


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--worker":
            raise SystemExit(worker_main(Path(sys.argv[2])))
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"Training refused/failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
