import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.security import AuthError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def validate_filename(name: str | None):
    if (
        not name
        or len(name) > 255
        or any(c in name for c in "/\\:\x00")
        or any(ord(c) < 32 for c in name)
    ):
        raise AuthError(422, "INVALID_FILENAME", "文件名无效，不能包含路径")
    suffix = Path(name).suffix.lower().lstrip(".")
    if suffix not in {"pdf", "docx", "txt", "md"}:
        raise AuthError(422, "UNSUPPORTED_TYPE", "仅支持 PDF、DOCX、TXT 和 MD 文件")
    return suffix


def store_upload(root: Path, file: UploadFile):
    raw_name = re.search(r'filename="([^"]*)"', file.headers.get("content-disposition", ""))
    if raw_name:
        validate_filename(raw_name.group(1))
    suffix = validate_filename(file.filename)
    root.mkdir(parents=True, exist_ok=True)
    key = str(uuid4())
    path = root / key
    digest = sha256()
    size = 0
    try:
        with path.open("xb") as target:
            while block := file.file.read(64 * 1024):
                size += len(block)
                if size > MAX_UPLOAD_BYTES:
                    raise AuthError(413, "FILE_TOO_LARGE", "文件不能超过 20 MiB")
                digest.update(block)
                target.write(block)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return key, digest.hexdigest(), suffix
