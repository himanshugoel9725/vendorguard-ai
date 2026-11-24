"""The demo script refuses unsafe DEMO_DIR values (nothing deleted); letta make targets fail."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _run_demo(demo_dir: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DEMO_DIR": demo_dir}
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "memory_demo.sh")],  # noqa: S607
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_absolute_tmp_dir_is_refused_and_kept(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    r = _run_demo(str(tmp_path))
    assert r.returncode == 2 and "refused" in r.stderr
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "value", ["..", "/", ".vendorguard", ".vendorguard/", ".vendorguard/../x", "other/dir"]
)
def test_unsafe_demo_dirs_are_refused(value: str) -> None:
    r = _run_demo(value)
    assert r.returncode == 2 and "refused" in r.stderr


def test_refusal_deletes_nothing_in_the_repo(tmp_path: Path) -> None:
    keep = ROOT / ".vendorguard"
    before = sorted(p.name for p in keep.iterdir()) if keep.exists() else []
    _run_demo(".vendorguard/../x")
    _run_demo(".vendorguard")
    after = sorted(p.name for p in keep.iterdir()) if keep.exists() else []
    assert before == after


@pytest.mark.parametrize("target", ["letta-up", "letta-down"])
def test_letta_targets_fail_and_mention_the_adr(target: str) -> None:
    r = subprocess.run(
        ["make", target],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode != 0
    assert "ADR-019" in r.stdout + r.stderr
