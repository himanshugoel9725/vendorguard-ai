"""loader.load_document: limits, errors, hashing, safety."""

import hashlib
import os
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from fpdf import FPDF
from pypdf import PdfWriter

from vendorguard.config import Settings
from vendorguard.errors import IngestError
from vendorguard.ingest.loader import load_document, sanitize_filename

Make = Callable[..., Settings]


def _pdf_bytes(*texts: str) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in texts:
        pdf.add_page()
        pdf.cell(text=text)
    return bytes(pdf.output())


def _write(path: Path, data: bytes | str) -> Path:
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


# load_document happy paths ----------------------------------------------------------------------


def test_text_file_loads_with_hash_identity(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override().ingest
    data = b"Vendor policy.\nSecond line."
    doc = load_document(_write(tmp_path / "policy.txt", data), ingest)
    digest = hashlib.sha256(data).hexdigest()
    assert doc.sha256 == digest
    assert doc.doc_id == digest[:16]
    assert doc.filename == "policy.txt"
    assert doc.media_type == "text/plain"
    assert [p.number for p in doc.pages] == [1]


def test_markdown_media_type(tmp_path: Path, settings_override: Make) -> None:
    doc = load_document(_write(tmp_path / "n.md", "# Title"), settings_override().ingest)
    assert doc.media_type == "text/markdown"


def test_pdf_loads(tmp_path: Path, settings_override: Make) -> None:
    path = _write(tmp_path / "s.pdf", _pdf_bytes("Alpha", "Beta"))
    doc = load_document(path, settings_override().ingest)
    assert doc.media_type == "application/pdf"
    assert [p.number for p in doc.pages] == [1, 2]
    assert "Beta" in doc.pages[1].text


def test_uppercase_extension_is_accepted(tmp_path: Path, settings_override: Make) -> None:
    doc = load_document(_write(tmp_path / "UP.TXT", "hi"), settings_override().ingest)
    assert doc.filename == "UP.TXT"
    assert doc.media_type == "text/plain"


def test_same_content_different_names_gives_same_id(
    tmp_path: Path, settings_override: Make
) -> None:
    ingest = settings_override().ingest
    a = load_document(_write(tmp_path / "a.txt", "same"), ingest)
    b = load_document(_write(tmp_path / "b.md", "same"), ingest)
    assert (a.doc_id, a.sha256) == (b.doc_id, b.sha256)
    assert a.filename != b.filename


def test_loading_twice_gives_equal_documents(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override().ingest
    path = _write(tmp_path / "d.txt", "a\fb")
    assert load_document(path, ingest) == load_document(path, ingest)


def test_symlink_to_a_file_loads(tmp_path: Path, settings_override: Make) -> None:
    target = _write(tmp_path / "real.txt", "linked text")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    doc = load_document(link, settings_override().ingest)
    assert doc.filename == "link.txt"
    assert doc.pages[0].text == "linked text"


def test_long_filename_is_shortened(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override().ingest
    path = _write(tmp_path / ("n" * 200 + ".txt"), "x")
    doc = load_document(path, ingest)
    assert len(doc.filename) == ingest.max_filename_chars
    assert doc.filename.endswith(".txt")


def test_loader_never_modifies_the_input(tmp_path: Path, settings_override: Make) -> None:
    path = _write(tmp_path / "keep.txt", b"\xef\xbb\xbfcrlf\r\ntext\f")
    before = (path.read_bytes(), path.stat().st_mtime_ns, sorted(os.listdir(tmp_path)))
    load_document(path, settings_override().ingest)
    assert (path.read_bytes(), path.stat().st_mtime_ns, sorted(os.listdir(tmp_path))) == before


def test_content_is_not_executed_or_interpreted(tmp_path: Path, settings_override: Make) -> None:
    marker = tmp_path / "pwned"
    payload = f"__import__('os').system('touch {marker}')\n$(touch {marker})\n`touch {marker}`"
    doc = load_document(_write(tmp_path / "evil.md", payload), settings_override().ingest)
    assert doc.pages[0].text == payload
    assert not marker.exists()


# load_document errors ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["tool.exe", "noext", "a.txt.exe", "x.PDF.sh"])
def test_disallowed_extension(tmp_path: Path, settings_override: Make, name: str) -> None:
    path = _write(tmp_path / name, "data")
    with pytest.raises(IngestError, match="is not allowed") as info:
        load_document(path, settings_override().ingest)
    assert str(info.value).startswith(sanitize_filename(name, 120))


def test_missing_file_and_directory_are_not_a_file(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override().ingest
    (tmp_path / "dir.txt").mkdir()
    for name in ("dir.txt", "ghost.txt"):
        with pytest.raises(IngestError, match=r"^" + name + ": not a file"):
            load_document(tmp_path / name, ingest)


def test_dangling_symlink_is_not_a_file(tmp_path: Path, settings_override: Make) -> None:
    link = tmp_path / "dangling.txt"
    link.symlink_to(tmp_path / "nowhere.txt")
    with pytest.raises(IngestError, match="not a file"):
        load_document(link, settings_override().ingest)


def test_size_limit_is_enforced_one_byte_over(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override(ingest={"max_file_mb": 1}).ingest
    limit = 1024 * 1024
    ok = _write(tmp_path / "ok.txt", b"a" * limit)
    assert load_document(ok, ingest).pages[0].text == "a" * limit
    big = _write(tmp_path / "big.txt", b"a" * (limit + 1))
    with pytest.raises(IngestError, match=r"^big\.txt: larger than the limit of 1 MB"):
        load_document(big, ingest)


def test_page_limit_comes_from_settings(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override(ingest={"max_pages": 2}).ingest
    path = _write(tmp_path / "p.txt", "a\fb\fc")
    with pytest.raises(IngestError, match=r"^p\.txt: .*more than the limit of 2"):
        load_document(path, ingest)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"caf\xe9", "not valid UTF-8"),
        (b"a\x00b", "NUL bytes"),
        (b"", "has no text"),
        (b" \n\t", "has no text"),
    ],
)
def test_bad_text_content(
    tmp_path: Path, settings_override: Make, data: bytes, message: str
) -> None:
    path = _write(tmp_path / "bad.txt", data)
    with pytest.raises(IngestError, match=r"^bad\.txt: .*" + message):
        load_document(path, settings_override().ingest)


def test_pdf_error_cases_name_the_file(tmp_path: Path, settings_override: Make) -> None:
    ingest = settings_override().ingest
    blank = PdfWriter()
    blank.add_blank_page(width=100, height=100)
    buf = BytesIO()
    blank.write(buf)
    enc = PdfWriter()
    enc.add_blank_page(width=100, height=100)
    enc.encrypt("pw")
    ebuf = BytesIO()
    enc.write(ebuf)
    cases = {
        "nohdr.pdf": (b"just text", "missing %PDF- header"),
        "corrupt.pdf": (b"%PDF-1.4\nnot really", "cannot be read"),
        "locked.pdf": (ebuf.getvalue(), "is encrypted"),
        "scan.pdf": (buf.getvalue(), "scanned PDFs need OCR"),
    }
    for name, (data, message) in cases.items():
        with pytest.raises(IngestError, match=rf"^{name}: .*{message}"):
            load_document(_write(tmp_path / name, data), ingest)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="needs non-root POSIX")
def test_unreadable_file_raises_ingest_error(tmp_path: Path, settings_override: Make) -> None:
    path = _write(tmp_path / "secret.txt", "x")
    os.chmod(path, 0o000)
    try:
        with pytest.raises(IngestError, match=r"^secret\.txt: cannot be read"):
            load_document(path, settings_override().ingest)
    finally:
        os.chmod(path, 0o600)


def test_file_disappearing_during_read_raises_ingest_error(
    tmp_path: Path, settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "gone.txt", "x")

    def boom(self: Path, *args: object, **kwargs: object) -> object:
        raise FileNotFoundError("vanished")

    ingest = settings_override().ingest  # read the settings before the patch takes effect
    monkeypatch.setattr(Path, "open", boom)
    with pytest.raises(IngestError, match=r"^gone\.txt: cannot be read \(FileNotFoundError\)"):
        load_document(path, ingest)
