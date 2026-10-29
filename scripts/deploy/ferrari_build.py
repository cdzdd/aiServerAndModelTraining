"""Build Ferrari's three-image export from a clean committed worktree, without secrets."""

import argparse
import ast
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

PLATFORM = "linux/amd64"
SOURCE_REPOSITORY = "https://github.com/cdzdd/aiServerAndModelTraining"
DB_IMAGE = "pgvector/pgvector:0.8.6-pg16-bookworm"
DB_BASE = DB_IMAGE + "@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b"
BASE_IMAGES = {
    "api": "python:3.12.11-slim-bookworm@sha256:"
    "519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7",
    "web": "caddy:2.10.2-alpine@sha256:"
    "4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d",
    "db": DB_BASE,
}


class BuildError(Exception):
    pass


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def docker(args, *, cwd=None, check=True):
    result = subprocess.run(
        ["docker", *args],
        cwd=cwd,
        check=check,
        stdout=subprocess.PIPE if args[:2] == ["image", "inspect"] else None,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout else None


def allowed_input(name):
    parts = PurePosixPath(name).parts
    excluded = {
        ".git",
        ".local",
        ".aws",
        ".ssh",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "test-results",
        "playwright-report",
        "uploads",
        "models",
        "checkpoints",
        "adapters",
    }
    if any(p in excluded or p == ".env" or p.startswith(".env.") for p in parts):
        return False
    if PurePosixPath(name).suffix in {".pem", ".key", ".log"}:
        return False
    return name in {
        ".dockerignore",
        "backend/Dockerfile",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/alembic.ini",
        "infra/Caddyfile.local",
        "scripts/deploy/smoke.py",
    } or name.startswith(("backend/app/", "backend/migrations/", "frontend/"))


def archive_context(root, commit, context):
    names = git(root, "ls-tree", "-r", "--name-only", "-z", commit).split("\0")
    names = [name for name in names if allowed_input(name)]
    archive = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", commit, "--", *names],
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            if member.isdir():
                continue
            if not member.isfile() or not allowed_input(member.name):
                raise BuildError(f"Unsupported committed build input: {member.name}")
            destination = context / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as content, destination.open("wb") as target:
                shutil.copyfileobj(content, target)
            destination.chmod(member.mode)


def model_metadata(context):
    tree = ast.parse((context / "backend/app/modules/retrieval/embedding.py").read_text("utf-8"))
    values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"MODEL_ID", "MODEL_REVISION", "DIMENSION", "_MODEL_FILES"}
    }
    return {
        "model": values["MODEL_ID"],
        "revision": values["MODEL_REVISION"],
        "dimensions": values["DIMENSION"],
        "path": "/opt/models/bge",
        "files": values["_MODEL_FILES"],
    }


def sha256(path):
    with path.open("rb") as content:
        return hashlib.file_digest(content, "sha256").hexdigest()


def copy_model(model_dir, context, files):
    for name, expected in files.items():
        source = model_dir / name
        target = context / "runtime-bge" / name
        try:
            if not source.is_file() or sha256(source) != expected:
                raise BuildError(f"Missing or corrupt BGE file: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)  # HF cache source links become ordinary files.
            target.chmod(0o644)
            if sha256(target) != expected:
                raise BuildError(f"Copied BGE file failed SHA256 validation: {name}")
        except OSError as exc:
            raise BuildError(f"Cannot copy BGE file: {name}") from exc


def build(root, model_dir, output_dir):
    root, model_dir, output_dir = root.resolve(), model_dir.resolve(), output_dir.resolve()
    commit = git(root, "rev-parse", "HEAD")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise BuildError("Build requires a clean committed worktree (ignored files are allowed).")
    try:
        relative_output = output_dir.relative_to(root).as_posix() + "/"
    except ValueError as exc:
        raise BuildError("Output directory must be inside the worktree and Git-ignored.") from exc
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", relative_output], check=False
    )
    if ignored.returncode != 0:
        raise BuildError("Output directory must be Git-ignored.")
    for name in ("images.tar", "build-report.json"):
        if (output_dir / name).exists():
            raise BuildError(f"Output already exists: {name}")

    images = {
        "api": f"ferrari-knowledge-qa-api:{commit[:12]}",
        "web": f"ferrari-knowledge-qa-web:{commit[:12]}",
        "db": DB_IMAGE,
    }
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        return docker(args, **kwargs)

    with tempfile.TemporaryDirectory(prefix="ferrari-build-") as temporary:
        context = Path(temporary) / "context"
        context.mkdir()
        archive_context(root, commit, context)
        embedding = model_metadata(context)
        copy_model(model_dir, context, embedding["files"])
        for role, dockerfile, target in [
            ("api", "backend/Dockerfile", ["--target", "ferrari"]),
            ("web", "frontend/Dockerfile", []),
        ]:
            run(
                [
                    "buildx",
                    "build",
                    "--platform",
                    PLATFORM,
                    "--provenance=false",
                    "--load",
                    "--label",
                    f"org.opencontainers.image.revision={commit}",
                    "--label",
                    f"org.opencontainers.image.source={SOURCE_REPOSITORY}",
                    "--file",
                    dockerfile,
                    *target,
                    "--tag",
                    images[role],
                    str(context),
                ],
                cwd=context,
            )
        run(["pull", "--platform", PLATFORM, DB_BASE])
        pinned_id = run(["image", "inspect", "--format", "{{.Id}}", DB_BASE])
        tag_id = run(["image", "inspect", "--format", "{{.Id}}", DB_IMAGE], check=False)
        if not pinned_id:
            raise BuildError("Cannot inspect pinned database image.")
        if tag_id and tag_id != pinned_id:
            raise BuildError(
                "Existing database tag differs from the pinned digest; refusing overwrite."
            )
        if not tag_id:
            run(["image", "tag", DB_BASE, DB_IMAGE])
        output_dir.mkdir(parents=True, exist_ok=True)
        # Save to a temporary file; a failed Docker export never looks like a completed export.
        pending = Path(temporary) / "images.tar"
        run(["image", "save", "--platform", PLATFORM, "--output", str(pending), *images.values()])
        report = {
            "runtimeType": "python-pgvector-v1",
            "sourceRepository": SOURCE_REPOSITORY,
            "sourceCommit": commit,
            "platform": PLATFORM,
            "images": images,
            "baseImages": BASE_IMAGES,
            "embedding": embedding,
            "files": {"images.tar": sha256(pending)},
            "commands": commands,
        }
        with (output_dir / "images.tar").open("xb") as target, pending.open("rb") as source:
            shutil.copyfileobj(source, target)
        with (output_dir / "build-report.json").open("x", encoding="utf-8") as target:
            json.dump(report, target, ensure_ascii=False, indent=2)
            target.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build(Path(__file__).resolve().parents[2], args.model_dir, args.output_dir)
    except (BuildError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Ferrari build failed: {exc}\n")
    print(f"Exported {report['sourceCommit']} to {args.output_dir}")


if __name__ == "__main__":
    main()
