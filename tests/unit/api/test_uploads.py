"""Tests for upload validation and the safe on-disk name (no network)."""

import asyncio
import io
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from vendorguard.api.uploads import (
    check_content,
    private_upload_dir,
    read_upload,
    save_upload,
)
from vendorguard.config import Settings

Make = Callable[..., Settings]
MB = 1024 * 1024


def upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


def run(name: str, data: bytes, s: Settings) -> tuple[str, str, bytes]:
    return asyncio.run(read_upload(upload(name, data), s))


def status_of(name: str, data: bytes, s: Settings) -> int:
    with pytest.raises(HTTPException) as exc:
        run(name, data, s)
    return exc.value.status_code


@pytest.fixture
def s(settings_override: Make) -> Settings:
    return settings_override()


@pytest.mark.parametrize(
    ("name", "data"),
    [("a.pdf", b"%PDF-1.7 x"), ("a.txt", "héllo ✓".encode()), ("A.MD", b"# title")],
)
def test_allowed_types_are_accepted(name: str, data: bytes, s: Settings) -> None:
    shown, ext, content = run(name, data, s)
    assert content == data and shown == name and ext == "." + name.rsplit(".", 1)[1].lower()


@pytest.mark.parametrize("name", ["a.exe", "a.html", "noext", "a.pdf.exe", "", ".pdf.sh"])
def test_other_types_are_415(name: str, s: Settings) -> None:
    assert status_of(name, b"data", s) == 415


def test_missing_filename_is_415(s: Settings) -> None:
    f = UploadFile(file=io.BytesIO(b"x"), filename=None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload(f, s))
    assert exc.value.status_code == 415


def test_pdf_without_magic_is_415(s: Settings) -> None:
    assert status_of("a.pdf", b"hello", s) == 415
    assert status_of("a.pdf", b" %PDF-1.4", s) == 415


@pytest.mark.parametrize("data", [b"ab\x00cd", b"\xff\xfe bad"])
def test_text_with_nul_or_bad_utf8_is_415(data: bytes, s: Settings) -> None:
    assert status_of("a.txt", data, s) == 415


@pytest.mark.parametrize("name", ["a.pdf", "a.txt"])
def test_empty_is_400(name: str, s: Settings) -> None:
    assert status_of(name, b"", s) == 400
    with pytest.raises(HTTPException) as exc:
        check_content(".txt", b"")
    assert exc.value.status_code == 400


def test_size_limit_is_exact(settings_override: Make) -> None:
    s = settings_override(api={"max_upload_mb": 1})
    limit = s.api.max_upload_mb * MB
    ok = b"a" * limit
    assert len(run("a.txt", ok, s)[2]) == limit
    assert status_of("a.txt", ok + b"a", s) == 413


def test_at_most_limit_plus_one_bytes_are_read(settings_override: Make) -> None:
    s = settings_override(api={"max_upload_mb": 1})
    limit = s.api.max_upload_mb * MB
    f = upload("a.txt", b"a" * (limit * 3))
    sizes: list[int | None] = []
    original = f.read

    async def spy(size: int = -1) -> bytes:
        sizes.append(size)
        return await original(size)

    f.read = spy  # type: ignore[method-assign]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload(f, s))
    assert exc.value.status_code == 413
    assert sizes == [limit + 1]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\win\\notes.txt", "notes.txt"),
        (".hidden.pdf", "hidden.pdf"),
        ("a b‮.txt", "a_b_.txt"),
    ],
)
def test_display_names_are_sanitised(name: str, expected: str, s: Settings) -> None:
    data = b"%PDF-1" if name.endswith(".pdf") else b"text"
    assert run(name, data, s)[0] == expected


def test_long_names_are_cut_keeping_extension(s: Settings) -> None:
    shown, _, _ = run("x" * 1000 + ".txt", b"t", s)
    assert len(shown) <= s.ingest.max_filename_chars and shown.endswith(".txt")


def test_double_dot_pdf_name_gives_a_validated_extension(s: Settings, tmp_path: Path) -> None:
    shown, ext, data = run("..pdf", b"%PDF-1", s)
    assert ext == ".pdf"
    p = save_upload(tmp_path, 0, ext, data)
    assert p == tmp_path / "upload_00.pdf" and p.read_bytes() == b"%PDF-1"


def test_extension_is_lowercased_and_from_the_last_suffix(s: Settings) -> None:
    assert run("Report.PDF", b"%PDF-1", s)[1] == ".pdf"
    assert run("a.b.TXT", b"t", s)[1] == ".txt"
    assert run("dir\\sub\\n.md", b"t", s)[1] == ".md"


def test_save_uses_a_server_chosen_name(tmp_path: Path) -> None:
    p = save_upload(tmp_path, 3, ".pdf", b"%PDF-1")
    assert p == tmp_path / "upload_03.pdf" and p.read_bytes() == b"%PDF-1"


@pytest.mark.parametrize("hostile", ["../../x.txt", "/etc/passwd.txt", "a/b\\c.md", "..txt"])
def test_hostile_client_names_never_escape_after_validation(
    tmp_path: Path, hostile: str, s: Settings
) -> None:
    folder = tmp_path / "up"
    folder.mkdir()
    _, ext, data = run(hostile, b"x", s)
    p = save_upload(folder, 12, ext, data)
    assert p.parent == folder and p.name == f"upload_12{ext}"
    assert [q.name for q in tmp_path.iterdir()] == ["up"]


def test_save_is_exclusive_and_private(tmp_path: Path) -> None:
    p = save_upload(tmp_path, 0, ".txt", b"first")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        save_upload(tmp_path, 0, ".txt", b"second")
    assert p.read_bytes() == b"first"


def test_save_refuses_a_planted_symlink(tmp_path: Path) -> None:
    target = tmp_path / "victim.txt"
    target.write_bytes(b"keep")
    folder = tmp_path / "up"
    folder.mkdir()
    (folder / "upload_00.txt").symlink_to(target)
    with pytest.raises(OSError):
        save_upload(folder, 0, ".txt", b"evil")
    assert target.read_bytes() == b"keep"


def test_private_upload_dir_is_new_private_and_server_named(tmp_path: Path) -> None:
    base = tmp_path / "deep" / "uploads"
    a = private_upload_dir(base)
    b = private_upload_dir(base)
    assert a != b and a.parent == base and b.parent == base
    assert a.name.startswith("upload_") and a.is_dir()
    assert stat.S_IMODE(os.stat(a).st_mode) == 0o700
