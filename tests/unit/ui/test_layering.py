"""ADR-021: the UI is a client of the REST API. It must not import server-side code, and only the
entry point ``app.py`` may load the settings."""

import ast
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[3] / "src" / "vendorguard" / "ui"
FORBIDDEN = (
    "vendorguard.pipeline",
    "vendorguard.api",
    "vendorguard.providers",
    "vendorguard.agents",
    "vendorguard.factory",
    "vendorguard.cli",
    "vendorguard.interfaces",
    "vendorguard.ingest",
    "vendorguard.retrieval",
    "vendorguard.scoring",
    "vendorguard.verification",
    "vendorguard.reporting",
    "vendorguard.observability",
    "vendorguard.eval",
)
FILES = sorted(UI.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_ui_files_exist() -> None:
    assert {p.name for p in FILES} >= {"app.py", "api_client.py", "progress.py", "validation.py"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(UI)))
def test_ui_imports_no_server_code(path: Path) -> None:
    bad = [n for n in _imports(path) if n.startswith(FORBIDDEN)]
    assert not bad, f"{path.name} imports server-side code: {bad}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(UI)))
def test_only_the_entry_point_loads_settings(path: Path) -> None:
    loads = "vendorguard.config" in _imports(path)
    assert loads == (path.name == "app.py"), f"{path.name}: settings may only be loaded by app.py"


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(UI)))
def test_ui_never_renders_untrusted_text_as_markup(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "unsafe_allow_html" not in text and "st.html" not in text


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(UI)))
def test_no_markdown_widgets_are_used_for_data(path: Path) -> None:
    """st.write and st.markdown render Markdown: the UI uses st.text, st.code or plain()."""
    text = path.read_text(encoding="utf-8")
    assert "st.write(" not in text and "st.markdown(" not in text
