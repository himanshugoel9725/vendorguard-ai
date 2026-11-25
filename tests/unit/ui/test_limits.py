"""Upload limits checked before any file is read."""

from vendorguard.ui.limits import BYTES_PER_MB, UploadLimits

LIMITS = UploadLimits(extensions=("pdf", "txt", "md"), max_file_mb=20, max_files=5)


def test_files_within_the_limits_are_fine() -> None:
    assert LIMITS.problems([("a.pdf", 1), ("b.txt", 20 * BYTES_PER_MB)]) == []


def test_too_many_and_too_large_are_reported_in_words() -> None:
    assert "At most 5 files" in LIMITS.problems([("a", 1)] * 6)[0]
    big = LIMITS.problems([("a", 20 * BYTES_PER_MB + 1), ("b", 1)])
    assert big == ["Each file may be at most 20 MB: 1 too large."]
    both = LIMITS.problems([("a", 21 * BYTES_PER_MB)] * 6)
    assert len(both) == 2
