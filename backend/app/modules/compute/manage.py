"""Explicit machine credential provisioning; tokens never appear in command arguments/output."""

import argparse
import getpass
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.modules.compute import service
from app.modules.compute.models import ComputeWorker


def write_private_config(path: Path, config: dict):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == "nt":
            # Windows ignores POSIX mode bits. Remove inherited ACLs before writing any secret.
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
                check=True,
                capture_output=True,
            )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            json.dump(config, output, ensure_ascii=False)
            output.write("\n")
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Provision or revoke a desktop compute node")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--name", required=True)
    register.add_argument("--model-id", required=True)
    register.add_argument("--cloud-url", required=True)
    register.add_argument("--model-base-url", default="http://127.0.0.1:11434")
    register.add_argument("--output", type=Path, required=True)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--worker-id", type=UUID, required=True)
    args = parser.parse_args(argv)

    # Loading database settings belongs only to the administrator command, never desktop imports.
    from app.core.config import Settings
    from app.core.database import create_db_engine
    from app.modules.auth import models as auth_models  # noqa: F401
    from app.modules.chat import models as chat_models  # noqa: F401

    engine = create_db_engine(Settings())
    try:
        factory = sessionmaker(engine)
        with factory.begin() as db:
            if args.command == "register":
                worker, token = service.register_worker(
                    db, name=args.name, model_id=args.model_id, now=datetime.now(UTC)
                )
                write_private_config(
                    args.output,
                    {
                        "cloud_url": args.cloud_url,
                        "token": token,
                        "model_id": args.model_id,
                        "model_base_url": args.model_base_url,
                        "ollama_num_ctx": 4096,
                    },
                )
                worker_id = worker.id
            else:
                worker = db.get(ComputeWorker, args.worker_id, with_for_update=True)
                if worker is None:
                    parser.error("Unknown compute worker")
                worker.is_active = False
                worker_id = worker.id
        print(f"Compute worker {worker_id}: {args.command}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
