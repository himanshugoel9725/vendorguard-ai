"""Offline replay of the committed cassettes: a real-model run, reproduced without a model.

The cassettes in ``tests/cassettes`` were recorded by ``make record`` (local Ollama, BM25
retrieval). Replay uses the Ollama provider in ``read_only`` cache mode, so any prompt, schema
or setting change that alters a request is a ``CacheMissError``: re-record with ``make record``.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
import respx

from vendorguard.config import Settings
from vendorguard.eval.golden import load_golden
from vendorguard.observability.run_manifest import result_hash
from vendorguard.pipeline.orchestrator import run_assessment

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ROOT / "tests" / "cassettes"
STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]
MAX_CASSETTE_BYTES = 2_000_000  # PLAN 6.7: cassettes stay under 2 MB
# Measured on the recorded run (qwen2.5:3b): 11, 18, 14 and 16 of 25. A floor, not a target:
# Phase 9 measures the models; this test only guards the pipeline against regressions.
MIN_ACCURACY = 0.40
Make = Callable[..., Settings]


@pytest.fixture
def replay(settings_override: Make) -> Callable[[], Settings]:
    def build() -> Settings:
        return settings_override(
            llm={"provider": "ollama"},
            embeddings={"provider": "none"},
            decision={"provider": "rule"},
            cache={
                "enabled": True,
                "backend": "jsonl",
                "mode": "read_only",
                "jsonl_dir": CASSETTES,
            },
        )

    return build


def test_cassettes_exist_and_are_small() -> None:
    files = sorted(CASSETTES.glob("*.jsonl"))
    assert files, "no cassettes: run `make record` (needs local Ollama)"
    assert sum(f.stat().st_size for f in files) < MAX_CASSETTE_BYTES


@pytest.mark.parametrize("stem", STEMS)
def test_replay_reproduces_the_recorded_run_offline(
    replay: Callable[[], Settings], stem: str
) -> None:
    golden = load_golden(ROOT / "data" / "golden" / f"{stem}.json")
    doc = ROOT / "data" / "samples" / f"{stem}.pdf"
    with respx.mock(assert_all_called=False) as network:  # any HTTP call would fail the test
        first = run_assessment(replay(), golden.vendor_id, [doc])
        second = run_assessment(replay(), golden.vendor_id, [doc])
        assert not network.calls
    assert result_hash(first) == result_hash(second)
    assert first.cost.llm_calls == 0 and first.cost.usd == 0  # everything came from the cassettes
    assert first.cost.cache_hits > 0
    assert first.inherent_risk.tier is golden.expected_inherent_tier
    hits = sum(f.status.value == golden.controls[f.control_id] for f in first.findings)
    assert hits / len(first.findings) >= MIN_ACCURACY
