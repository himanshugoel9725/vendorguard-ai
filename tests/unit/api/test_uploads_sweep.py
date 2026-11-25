"""Stale uploads are swept at start-up; the upload parent folder is private (audit 11.1, L3)."""

import os
import stat
from pathlib import Path

from vendorguard.api import uploads
from vendorguard.api.uploads import private_upload_dir, sweep_stale_uploads


def test_private_upload_dir_makes_the_parent_private(tmp_path: Path) -> None:
    base = tmp_path / "state" / "uploads"
    folder = private_upload_dir(base)
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and folder.parent == base


def test_sweep_removes_only_old_upload_folders(tmp_path: Path) -> None:
    base = tmp_path / "uploads"
    old, fresh = private_upload_dir(base), private_upload_dir(base)
    (old / "upload_00.txt").write_text("secret vendor text", encoding="utf-8")
    other = base / "keep_me"
    other.mkdir()
    long_ago = uploads.utcnow().timestamp() - 7200
    os.utime(old, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    assert sweep_stale_uploads(base, 3600) == 1
    assert not old.exists() and fresh.exists() and other.exists()  # only upload_* folders count


def test_sweep_with_no_folder_is_fine(tmp_path: Path) -> None:
    assert sweep_stale_uploads(tmp_path / "missing", 60) == 0


def test_sweep_does_not_follow_symlinks(tmp_path: Path) -> None:
    base = tmp_path / "uploads"
    base.mkdir()
    target = tmp_path / "precious"
    target.mkdir()
    link = base / "upload_link"
    link.symlink_to(target, target_is_directory=True)
    long_ago = uploads.utcnow().timestamp() - 7200
    os.utime(target, (long_ago, long_ago))
    assert sweep_stale_uploads(base, 3600) == 0 and target.exists()
