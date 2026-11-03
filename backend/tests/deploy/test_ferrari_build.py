import ast
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/ferrari_build.py"


def test_build_entry_exists():
    assert SCRIPT.is_file(), "Ferrari's committed-source build entry is missing"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def build_module():
    spec = importlib.util.spec_from_file_location("ferrari_build", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "core.autocrlf", "false")
    git(root, "remote", "add", "origin", "https://github.com/cdzdd/aiServerAndModelTraining.git")
    for name in [
        "backend/Dockerfile",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/alembic.ini",
        "backend/app/main.py",
        "backend/migrations/env.py",
        "frontend/Dockerfile",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/src/main.ts",
        "infra/Caddyfile.local",
        "scripts/deploy/smoke.py",
        "frontend/.env.committed",
        "frontend/node_modules/private.txt",
        "frontend/uploads/private.txt",
        "backend/app/.env",
        "unrelated-secret.txt",
    ]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("committed " + name, encoding="utf-8")
    (root / ".gitignore").write_text(".local/\n.env\n", encoding="utf-8")
    (root / ".dockerignore").write_bytes((ROOT / ".dockerignore").read_bytes())
    model = tmp_path / "model"
    model.mkdir()
    tree = ast.parse((ROOT / "backend/app/modules/retrieval/embedding.py").read_text("utf-8"))
    names = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "_MODEL_FILES"
    )
    hashes = {}
    for name in names:
        data = ("fixture model " + name).encode()
        target = model / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    metadata = root / "backend/app/modules/retrieval/embedding.py"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        'MODEL_ID = "BAAI/bge-small-zh-v1.5"\n'
        'MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"\n'
        f"DIMENSION = 512\n_MODEL_FILES = {hashes!r}\n",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    output = root / ".local/output"
    return root, model, output, hashes


@pytest.fixture
def docker_stub(build_module, monkeypatch):
    calls = []
    contexts = []
    state = {
        "tag_id": None,
        "fail": None,
        "api": "1.52",
        "driver": "overlayfs",
        "driver_status": [["driver-type", "io.containerd.snapshotter.v1"]],
        "inspections": {},
    }
    pinned_id = "sha256:" + "a" * 64

    def docker(args, *, cwd=None, check=True):
        calls.append(args)
        if state["fail"] and args[: len(state["fail"])] == state["fail"]:
            raise subprocess.CalledProcessError(1, ["docker", *args])
        if args[:2] == ["buildx", "build"]:
            context = Path(args[-1])
            contexts.append(
                {
                    str(p.relative_to(context)).replace("\\", "/"): p.read_bytes()
                    for p in context.rglob("*")
                    if p.is_file()
                }
            )
            assert not any(p.is_symlink() for p in context.rglob("*"))
        if args[:2] == ["image", "inspect"]:
            target = args[-1]
            if args[args.index("--format") + 1] == "{{json .}}":
                return json.dumps(
                    state["inspections"].get(
                        target,
                        {
                            "Id": pinned_id
                            if target == build_module.DB_IMAGE
                            else "sha256:" + hashlib.sha256(target.encode()).hexdigest(),
                            "Os": "linux",
                            "Architecture": "amd64",
                        },
                    )
                )
            if target == build_module.DB_IMAGE and state["tag_id"] is None:
                return None
            return state["tag_id"] if target == build_module.DB_IMAGE else pinned_id
        if args[:2] == ["image", "tag"]:
            state["tag_id"] = pinned_id
        if args[0] == "version":
            return state["api"]
        if args[0] == "info":
            return (
                json.dumps(state["driver_status"])
                if "{{json .DriverStatus}}" in args
                else state["driver"]
            )
        if args[:2] == ["image", "save"]:
            Path(args[args.index("--output") + 1]).write_bytes(b"fixture docker archive")
        return ""

    monkeypatch.setattr(build_module, "docker", docker)
    return calls, contexts, state


def test_build_exports_only_committed_allowed_inputs(source, build_module, docker_stub):
    root, model, output, hashes = source
    (root / ".env").write_text("never read this invalid env\nSECRET=value", encoding="utf-8")
    (model / "token").write_text("private hub token", encoding="utf-8")
    (root / ".local").mkdir()
    (root / ".local/private.txt").write_text("private", encoding="utf-8")
    commit = git(root, "rev-parse", "HEAD")
    build_module.build(root, model, output)
    calls, contexts, _ = docker_stub
    context = contexts[0]
    assert context["frontend/src/main.ts"] == b"committed frontend/src/main.ts"
    assert all(
        ".env" not in name
        and "node_modules" not in name
        and "uploads" not in name
        and ".local" not in Path(name).parts
        and ".git/" not in name
        and "unrelated" not in name
        for name in context
    )
    copied = {
        name.removeprefix("runtime-bge/"): data
        for name, data in context.items()
        if name.startswith("runtime-bge/")
    }
    assert {name: hashlib.sha256(data).hexdigest() for name, data in copied.items()} == hashes
    build_calls = [call for call in calls if call[:2] == ["buildx", "build"]]
    assert len(build_calls) == 2
    for call in build_calls:
        assert call[call.index("--platform") + 1] == "linux/amd64"
        assert "--provenance=false" in call and "--load" in call
        assert f"org.opencontainers.image.revision={commit}" in call
        assert (
            "org.opencontainers.image.source=https://github.com/cdzdd/aiServerAndModelTraining"
            in call
        )
    assert build_calls[0][build_calls[0].index("--target") + 1] == "ferrari"
    assert f"ferrari-knowledge-qa-api:{commit[:12]}" in build_calls[0]
    assert f"ferrari-knowledge-qa-web:{commit[:12]}" in build_calls[1]
    pull = next(call for call in calls if call[0] == "pull")
    assert build_module.DB_BASE in pull and "linux/amd64" in pull
    save = next(call for call in calls if call[:2] == ["image", "save"])
    assert save[-3:] == [
        f"ferrari-knowledge-qa-api:{commit[:12]}",
        f"ferrari-knowledge-qa-web:{commit[:12]}",
        build_module.DB_IMAGE,
    ]
    assert save[save.index("--platform") + 1] == "linux/amd64"
    assert (output / "images.tar").read_bytes() == b"fixture docker archive"
    report = json.loads((output / "build-report.json").read_text("utf-8"))
    assert report["sourceCommit"] == commit
    assert report["platform"] == "linux/amd64"
    assert report["embedding"]["files"] == hashes
    assert report["images"]["db"] == build_module.DB_IMAGE
    assert report["files"]["images.tar"] == hashlib.sha256(b"fixture docker archive").hexdigest()
    assert "imageIds" not in report  # Docker29 inspect IDs may be OCI indexes.
    assert set(report["imageInspection"]) == {"api", "web", "db"}
    assert report["exportCompatibility"]["savePlatformFlag"] is True
    assert report["commands"] == calls
    assert "SECRET" not in (output / "build-report.json").read_text("utf-8")


@pytest.mark.parametrize("change", ["tracked", "staged", "untracked"])
def test_rejects_uncommitted_code(source, build_module, docker_stub, change):
    root, model, output, _ = source
    target = root / ("frontend/src/new.ts" if change == "untracked" else "frontend/src/main.ts")
    target.write_text("uncommitted", encoding="utf-8")
    if change == "staged":
        git(root, "add", ".")
    with pytest.raises(build_module.BuildError, match="clean"):
        build_module.build(root, model, output)
    assert docker_stub[0] == []
    assert not output.exists()


@pytest.mark.parametrize("problem", ["missing", "corrupt"])
def test_rejects_invalid_model_before_docker(source, build_module, docker_stub, problem):
    root, model, output, _ = source
    target = model / "model.safetensors"
    if problem == "missing":
        target.unlink()
    else:
        target.write_bytes(b"corrupt")
    with pytest.raises(build_module.BuildError, match="model.safetensors"):
        build_module.build(root, model, output)
    assert docker_stub[0] == []
    assert not (output / "build-report.json").exists()


def test_materializes_huggingface_links(source, build_module, docker_stub):
    root, model, output, _ = source
    original = model / "model.safetensors"
    blob = model.parent / "blob"
    original.rename(blob)
    try:
        original.symlink_to(blob)
    except OSError:
        pytest.skip("Host cannot create source symlinks")
    build_module.build(root, model, output)
    assert docker_stub[1][0]["runtime-bge/model.safetensors"] == blob.read_bytes()


@pytest.mark.parametrize("existing", ["images.tar", "build-report.json"])
def test_refuses_overwrite(source, build_module, docker_stub, existing):
    root, model, output, _ = source
    output.mkdir(parents=True)
    (output / existing).write_text("keep", encoding="utf-8")
    with pytest.raises(build_module.BuildError, match="exists"):
        build_module.build(root, model, output)
    assert (output / existing).read_text("utf-8") == "keep"
    assert docker_stub[0] == []


def test_requires_ignored_output(source, build_module, docker_stub):
    root, model, _, _ = source
    with pytest.raises(build_module.BuildError, match="ignored"):
        build_module.build(root, model, root / "artifacts")
    assert docker_stub[0] == []


@pytest.mark.parametrize("phase", [["buildx", "build"], ["image", "save"]])
def test_docker_failure_leaves_no_success_report(source, build_module, docker_stub, phase):
    root, model, output, _ = source
    docker_stub[2]["fail"] = phase
    with pytest.raises(subprocess.CalledProcessError):
        build_module.build(root, model, output)
    assert not (output / "build-report.json").exists()
    assert not (output / "images.tar").exists()


def test_refuses_conflicting_database_tag(source, build_module, docker_stub):
    root, model, output, _ = source
    docker_stub[2]["tag_id"] = "sha256:different"
    with pytest.raises(build_module.BuildError, match="database tag"):
        build_module.build(root, model, output)
    assert not (output / "build-report.json").exists()
    assert not any(call[:2] == ["image", "tag"] for call in docker_stub[0])


def test_docker26_classic_export_omits_only_save_platform_flag(source, build_module, docker_stub):
    root, model, output, _ = source
    calls, _, state = docker_stub
    state.update(api="1.45", driver="overlay2", driver_status=[["Backing Filesystem", "extfs"]])
    report = build_module.build(root, model, output)
    saves = [call for call in calls if call[:2] == ["image", "save"]]
    assert len(saves) == 1 and "--platform" not in saves[0]
    assert all("--platform" in call for call in calls if call[:2] == ["buildx", "build"])
    assert report["exportCompatibility"] == {
        "serverApiVersion": "1.45",
        "storageDriver": "overlay2",
        "imageStore": "classic",
        "savePlatformFlag": False,
    }
    inspect_calls = [call for call in calls if "{{json .}}" in call]
    assert len(inspect_calls) == 3
    assert max(calls.index(call) for call in inspect_calls) < calls.index(saves[0])
    assert report["commands"] == calls


@pytest.mark.parametrize("role", ["api", "web", "db"])
@pytest.mark.parametrize("platform", [("linux", "arm64"), ("windows", "amd64")])
def test_wrong_platform_is_rejected_before_any_export(
    source, build_module, docker_stub, role, platform
):
    root, model, output, _ = source
    commit = git(root, "rev-parse", "HEAD")
    target = build_module.DB_IMAGE if role == "db" else f"ferrari-knowledge-qa-{role}:{commit[:12]}"
    docker_stub[2]["inspections"][target] = {
        "Id": "sha256:" + "a" * 64,
        "Os": platform[0],
        "Architecture": platform[1],
    }
    with pytest.raises(build_module.BuildError, match="linux/amd64"):
        build_module.build(root, model, output)
    assert not any(call[:2] == ["image", "save"] for call in docker_stub[0])
    assert not (output / "images.tar").exists()
    assert not (output / "build-report.json").exists()


@pytest.mark.parametrize(
    "problem",
    ["containerd", "unknown-driver", "malformed-version", "malformed-store", "store-marker"],
)
def test_old_api_requires_verified_classic_store(source, build_module, docker_stub, problem):
    root, model, output, _ = source
    state = docker_stub[2]
    state["api"] = "1.45"
    if problem == "unknown-driver":
        state.update(driver="unknown", driver_status=[])
    elif problem == "malformed-version":
        state["api"] = "unverified"
    elif problem == "malformed-store":
        state.update(driver="overlay2", driver_status={})
    elif problem == "store-marker":
        state["driver"] = "overlay2"
    with pytest.raises(build_module.BuildError, match="Docker"):
        build_module.build(root, model, output)
    assert not any(call[:2] == ["image", "save"] for call in docker_stub[0])
    assert not (output / "build-report.json").exists()


@pytest.mark.parametrize("image_id", [None, "sha256:truncated", "sha256:" + "b" * 64])
def test_database_id_must_be_real_and_still_pinned_before_export(
    source, build_module, docker_stub, image_id
):
    root, model, output, _ = source
    docker_stub[2]["inspections"][build_module.DB_IMAGE] = {
        "Id": image_id,
        "Os": "linux",
        "Architecture": "amd64",
    }
    with pytest.raises(build_module.BuildError):
        build_module.build(root, model, output)
    assert not any(call[:2] == ["image", "save"] for call in docker_stub[0])
    assert not (output / "images.tar").exists()


def test_api148_retains_platform_filter_on_classic_store(source, build_module, docker_stub):
    root, model, output, _ = source
    docker_stub[2].update(api="1.48", driver="overlay2", driver_status=[])
    report = build_module.build(root, model, output)
    save = next(call for call in docker_stub[0] if call[:2] == ["image", "save"])
    assert save[save.index("--platform") + 1] == "linux/amd64"
    assert report["exportCompatibility"]["savePlatformFlag"]


def test_dockerfile_keeps_default_local_target():
    text = (ROOT / "backend/Dockerfile").read_text("utf-8")
    assert " AS runtime\n" in text
    assert "FROM runtime AS ferrari\nCOPY runtime-bge /opt/models/bge" in text
    assert text.rstrip().endswith("FROM runtime AS local")
