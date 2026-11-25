"""The metrics on a real (mock-LLM) pipeline run: matches the hand count of the golden labels."""

from collections.abc import Callable
from pathlib import Path

from vendorguard.config import Settings
from vendorguard.eval.golden import load_golden
from vendorguard.eval.metrics import evaluate
from vendorguard.pipeline.orchestrator import run_assessment

ROOT = Path(__file__).resolve().parents[2]


def test_quillfield_mock_run_is_scored(settings_override: Callable[..., Settings]) -> None:
    golden = load_golden(ROOT / "data" / "golden" / "quillfield.json")
    result = run_assessment(
        settings_override(), golden.vendor_id, [ROOT / "data" / "samples" / "quillfield.txt"]
    )
    m = evaluate(result.findings, golden.controls)
    hits = sum(f.status.value == golden.controls[f.control_id] for f in result.findings)
    assert m.controls == 25 and m.accuracy == hits / 25
    assert sum(sum(row.values()) for row in m.confusion.values()) == 25
    assert m.human_review_rate == 0.0
    assert m.citation_validity_rate == 1.0
    assert 0.0 <= m.triage_skip_rate <= 1.0
