"""Query built from a control."""

from pathlib import Path

from vendorguard.controls.loader import load_controls
from vendorguard.retrieval.query_builder import build_query


def test_query_holds_title_requirement_and_every_keyword(project_root: Path) -> None:
    controls = load_controls(project_root / "config/controls/baseline_v1.yaml").controls
    for control in controls:
        query = build_query(control)
        assert control.title in query and control.requirement in query
        assert all(keyword in query for keyword in control.keywords)
        assert query == build_query(control)
