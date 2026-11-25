"""scripts/build_demo.py: copies replayed reports and writes an escaped index."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_demo", ROOT / "scripts" / "build_demo.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(base: Path, name: str, vendor: str, overall: float = 12.5) -> Path:
    folder = base / "run_abc"
    folder.mkdir(parents=True)
    result = {"profile": {"vendor_name": vendor}, "score": {"overall": overall, "band": "low"}}
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (folder / "report.html").write_text(f"<html>{name}</html>", encoding="utf-8")
    return base


def test_build_copies_reports_and_escapes_the_index(demo: ModuleType, tmp_path: Path) -> None:
    runs = {
        "b": _run(tmp_path / "rb", "b", "<script>alert(1)</script> Corp"),
        "a": _run(tmp_path / "ra", "a", "Alpha & Co"),
    }
    index = demo.build(tmp_path / "site", runs)
    page = index.read_text(encoding="utf-8")
    assert (tmp_path / "site" / "demo" / "a.html").read_text(encoding="utf-8") == "<html>a</html>"
    assert "<script>" not in page and "&lt;script&gt;" in page and "Alpha &amp; Co" in page
    assert page.index('href="a.html"') < page.index('href="b.html"')  # sorted by stem
    assert "SYNTHETIC" in page and "12.5" in page


def test_a_runs_folder_must_hold_exactly_one_run(demo: ModuleType, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit, match="exactly one"):
        demo.find_run(empty)
    two = _run(tmp_path / "two", "x", "X")
    (two / "run_def").mkdir()
    (two / "run_def" / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly one"):
        demo.find_run(two)


def test_main_usage_and_success(demo: ModuleType, tmp_path: Path) -> None:
    assert demo.main(["only-site"]) == 2
    assert demo.main([str(tmp_path / "s"), "notapair"]) == 2
    runs = _run(tmp_path / "r", "q", "Quill")
    assert demo.main([str(tmp_path / "s"), f"q={runs}"]) == 0
    assert (tmp_path / "s" / "demo" / "index.html").is_file()


def test_demo_names_cannot_escape_the_demo_folder(demo: ModuleType, tmp_path: Path) -> None:
    runs = _run(tmp_path / "r", "q", "Quill")
    for bad in ("../evil", "a/b", "", "x" * 65):
        with pytest.raises(SystemExit, match="invalid demo name"):
            demo.build(tmp_path / "site", {bad: runs})
