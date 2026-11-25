"""Upload validation: type, content check, size and a safe on-disk name."""

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from vendorguard.config import Settings
from vendorguard.ingest.loader import MEDIA_TYPES, sanitize_filename
from vendorguard.utils.timeutil import utcnow

PDF_MAGIC = b"%PDF-"
BYTES_PER_MB = 1024 * 1024


def _extension(name: str, settings: Settings) -> str:
    ext = Path(name.replace("\\", "/")).suffix.lower()
    if ext not in settings.ingest.allowed_extensions or ext not in MEDIA_TYPES:
        allowed = ", ".join(settings.ingest.allowed_extensions)
        raise HTTPException(status_code=415, detail=f"unsupported file type (allowed: {allowed})")
    return ext


def check_content(ext: str, data: bytes) -> None:
    """The bytes must really be what the extension claims (magic bytes, no NUL, UTF-8)."""
    if not data:
        raise HTTPException(status_code=400, detail="the file is empty")
    if ext == ".pdf":
        if not data.startswith(PDF_MAGIC):
            raise HTTPException(status_code=415, detail="the file is not a PDF")
        return
    if b"\x00" in data:
        raise HTTPException(status_code=415, detail="the file is not text")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="the file is not UTF-8 text") from exc


async def read_form(request: Request, settings: Settings) -> FormData:
    """The multipart form of an upload request with the part counts capped (the body size is
    already capped by ``AccessGate``): too many files or fields is a 413, a broken form a 400.
    Upload routes call this instead of declaring ``UploadFile`` parameters."""
    api = settings.api
    try:
        return await request.form(
            max_files=api.max_files_per_request, max_fields=api.max_form_fields
        )
    except (MultiPartException, StarletteHTTPException) as exc:
        # Inside a real app Starlette has already turned MultiPartException into ITS OWN
        # HTTPException(400), the base class of FastAPI's (so catch the base).
        message = exc.message if isinstance(exc, MultiPartException) else str(exc.detail)
        too_many = "too many" in message.lower()
        raise HTTPException(
            status_code=413 if too_many else 400,
            detail="too many files or fields" if too_many else "the form is not valid",
        ) from exc


async def read_upload(upload: UploadFile, settings: Settings) -> tuple[str, str, bytes]:
    """The sanitised display name, the VALIDATED extension and the content of one upload.

    At most ``api.max_upload_mb`` + 1 byte is read (413 above the limit).
    """
    ext = _extension(upload.filename or "", settings)
    limit = settings.api.max_upload_mb * BYTES_PER_MB
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"the file is larger than {settings.api.max_upload_mb} MB"
        )
    check_content(ext, data)
    shown = sanitize_filename(upload.filename or "", settings.ingest.max_filename_chars)
    return shown, ext, data


def private_upload_dir(base: Path) -> Path:
    """A new folder under ``base`` that only this user can read (mode 0700), with a name the
    server chooses (never a client value)."""
    base.mkdir(parents=True, exist_ok=True)
    base.chmod(0o700)  # names of pending uploads are not for other local users either
    return Path(tempfile.mkdtemp(prefix="upload_", dir=base))


def sweep_stale_uploads(base: Path, max_age_s: float) -> int:
    """Delete upload folders under ``base`` older than ``max_age_s`` (left behind when the process
    was killed mid-run). Returns how many were removed; a missing ``base`` is fine."""
    if not base.is_dir():
        return 0
    cutoff = utcnow().timestamp() - max_age_s
    removed = 0
    for folder in sorted(base.glob("upload_*")):
        if folder.is_dir() and not folder.is_symlink() and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


def save_upload(folder: Path, index: int, ext: str, data: bytes) -> Path:
    """Write ``data`` as ``upload_NN<ext>`` in ``folder``: a SERVER-CHOSEN name, created
    exclusively (never overwriting or following a link), readable by this user only. ``ext`` is
    the extension ``read_upload`` validated."""
    path = folder / f"upload_{index:02d}{ext}"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return path


__all__ = [
    "PDF_MAGIC",
    "check_content",
    "private_upload_dir",
    "read_form",
    "read_upload",
    "save_upload",
    "sweep_stale_uploads",
]
