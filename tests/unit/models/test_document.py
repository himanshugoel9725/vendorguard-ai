"""Tests for vendorguard.models.document."""

import pytest
from pydantic import ValidationError

from vendorguard.models.document import Document, Page

SHA = "ab" * 32


def make_doc(pages: list[Page] | None = None, **kw: object) -> Document:
    if pages is None:
        pages = [Page(number=1, text="a"), Page(number=2, text="é漢")]
    data: dict = {
        "doc_id": SHA[:12],
        "filename": "f.pdf",
        "media_type": "application/pdf",
        "sha256": SHA,
        "pages": pages,
    }
    data.update(kw)
    return Document(**data)


def test_valid_and_roundtrip() -> None:
    d = make_doc()
    assert Document.model_validate_json(d.model_dump_json()) == d


def test_empty_pages_accepted() -> None:
    assert make_doc(pages=[]).pages == []


@pytest.mark.parametrize("n", [0, -1])
def test_page_number_min(n: int) -> None:
    with pytest.raises(ValidationError):
        Page(number=n, text="x")


@pytest.mark.parametrize(
    "numbers",
    [[1, 3], [1, 1], [0, 1], [2, 3], [2, 1]],
)
def test_bad_page_order(numbers: list[int]) -> None:
    with pytest.raises(ValidationError):
        make_doc(pages=[Page(number=n, text="") for n in numbers])


@pytest.mark.parametrize("sha", ["A" * 64, "a" * 63, "z" * 64, ""])
def test_bad_sha(sha: str) -> None:
    with pytest.raises(ValidationError):
        make_doc(sha256=sha)


def test_frozen_and_extra() -> None:
    d = make_doc()
    with pytest.raises(ValidationError):
        d.filename = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        make_doc(bogus=1)


def test_large_document() -> None:
    pages = [Page(number=i, text="x" * 1000) for i in range(1, 501)]
    assert len(make_doc(pages=pages).pages) == 500
