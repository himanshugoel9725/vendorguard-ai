"""Upload limits the page checks before reading a file (mirrors the API's, built by app.py)."""

from dataclasses import dataclass

BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class UploadLimits:
    """File types, size per file and number of files the API accepts."""

    extensions: tuple[str, ...]  # without the dot: ("pdf", "txt", "md")
    max_file_mb: int
    max_files: int

    def problems(self, files: list[tuple[str, int]]) -> list[str]:
        """What is wrong with ``(name, size)`` pairs, in words ([] if all is fine)."""
        out = []
        if len(files) > self.max_files:
            out.append(f"At most {self.max_files} files per assessment.")
        too_big = [n for n, size in files if size > self.max_file_mb * BYTES_PER_MB]
        if too_big:
            out.append(f"Each file may be at most {self.max_file_mb} MB: {len(too_big)} too large.")
        return out


__all__ = ["BYTES_PER_MB", "UploadLimits"]
