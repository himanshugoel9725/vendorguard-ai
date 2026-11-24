"""Tests for the audit log, the run manifest and the metrics."""

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.run import (
    AssessmentResult,
    CostSummary,
    ManifestInput,
    RunStatus,
)
from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore
from vendorguard.models.vendor import DataCategory, VendorProfile
from vendorguard.observability.audit_log import AuditLog, read_audit_log
from vendorguard.observability.metrics import Metrics
from vendorguard.observability.run_manifest import (
    current_git_sha,
    finish_manifest,
    read_manifest,
    result_hash,
    start_manifest,
    write_manifest,
)

SHA = "ab" * 32


def _record(log: AuditLog, stage: str = "mapper", **kw: object) -> AuditEvent:
    args: dict = {
        "stage": stage,
        "actor": "mock",
        "input_hash": SHA,
        "output_hash": SHA,
        "tokens_in": 3,
        "tokens_out": 2,
        "usd": 0.0,
        "latency_ms": 12.0,
        "cached": False,
    }
    args.update(kw)
    return log.record(**args)


def test_events_are_written_and_readable(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "run" / "audit.jsonl", "r1")
    first = _record(log, control_id="IAM-01")
    _record(log, "judge")
    events = read_audit_log(log.path)
    assert [e.seq for e in events] == [0, 1]
    assert events[0] == first and events[0].run_id == "r1" and events[0].control_id == "IAM-01"
    assert log.events() == events


def test_reopening_continues_the_sequence(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _record(AuditLog(path, "r1"))
    assert _record(AuditLog(path, "r1")).seq == 1


def test_threads_get_unique_increasing_seq(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.jsonl", "r1")
    threads = [threading.Thread(target=lambda: [_record(log) for _ in range(20)]) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [e.seq for e in read_audit_log(log.path)] == list(range(100))


def test_missing_file_reads_empty_and_damage_is_a_config_error(tmp_path: Path) -> None:
    assert read_audit_log(tmp_path / "none.jsonl") == []
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="line 1"):
        read_audit_log(bad)


def test_non_increasing_seq_is_refused(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.jsonl", "r1")
    _record(log)
    line = log.path.read_text(encoding="utf-8")
    log.path.write_text(line + line, encoding="utf-8")
    with pytest.raises(ConfigError, match="does not increase"):
        read_audit_log(log.path)


def test_on_event_callback_sees_every_event(tmp_path: Path) -> None:
    seen: list[AuditEvent] = []
    _record(AuditLog(tmp_path / "a.jsonl", "r1", on_event=seen.append))
    assert [e.seq for e in seen] == [0]


def _result(summary: str = "s", **kw: object) -> AssessmentResult:
    data: dict = {
        "run_id": "r1",
        "vendor_id": "v1",
        "created_at": datetime(2025, 1, 1, tzinfo=UTC),
        "profile": VendorProfile(
            vendor_name="Acme",
            services=["crm"],
            data_categories=[DataCategory.PII],
            hosting=[],
            certifications=[],
            subprocessors=[],
        ),
        "inherent_risk": InherentRisk(tier=InherentTier.MEDIUM, reasons=["pii"]),
        "findings": [],
        "score": RiskScore(
            overall=10.0, band=RiskBand.LOW, domain_scores={"AC": 10.0}, triggered_rules=[]
        ),
        "summary": summary,
        "cost": CostSummary(
            llm_calls=1, cache_hits=0, tokens_in=1, tokens_out=1, decider_calls=0, usd=0.0
        ),
    }
    data.update(kw)
    return AssessmentResult(**data)


def test_result_hash_ignores_volatile_fields_only() -> None:
    base = _result()
    volatile = _result(
        created_at=datetime(2030, 5, 5, tzinfo=UTC),
        cost=CostSummary(
            llm_calls=9, cache_hits=9, tokens_in=9, tokens_out=9, decider_calls=9, usd=1.0
        ),
        manifest_path=Path("x/manifest.json"),
    )
    assert result_hash(base) == result_hash(volatile)
    assert result_hash(base) != result_hash(_result("different"))


@pytest.fixture
def manifest_args() -> dict:
    return {
        "controls_version": "baseline_v1",
        "prompt_hashes": {"mapper": SHA, "intake": SHA},
        "providers": {"llm": "mock", "decider": "rule"},
        "inputs": [
            ManifestInput(filename="b.txt", sha256=SHA, pages=1),
            ManifestInput(filename="a.txt", sha256=SHA, pages=2),
        ],
    }


def test_manifest_round_trip_has_no_secrets_and_is_sorted(
    settings_override: Callable[..., Settings], tmp_path: Path, manifest_args: dict
) -> None:
    settings = settings_override()
    m = start_manifest("r1", settings, **manifest_args)
    assert m.status is RunStatus.RUNNING and m.config_fingerprint == settings.fingerprint()
    assert [i.filename for i in m.inputs] == ["a.txt", "b.txt"]
    done = finish_manifest(m, RunStatus.DONE, SHA)
    path = tmp_path / "manifest.json"
    write_manifest(path, done)
    assert read_manifest(path) == done
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["result_hash"] == SHA


def test_finish_rules(settings_override: Callable[..., Settings], manifest_args: dict) -> None:
    m = start_manifest("r1", settings_override(), **manifest_args)
    with pytest.raises(ConfigError):
        finish_manifest(m, RunStatus.RUNNING)
    with pytest.raises(ConfigError):
        finish_manifest(m, RunStatus.DONE)
    failed = finish_manifest(m, RunStatus.FAILED, SHA)
    assert failed.status is RunStatus.FAILED and failed.result_hash is None
    assert failed.finished_at is not None


def test_read_manifest_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        read_manifest(tmp_path / "m.json")
    (tmp_path / "m.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="damaged"):
        read_manifest(tmp_path / "m.json")


def test_git_sha_is_none_outside_a_checkout(tmp_path: Path, project_root: Path) -> None:
    assert current_git_sha(tmp_path, 5.0) is None
    sha = current_git_sha(project_root, 5.0)
    assert sha is None or len(sha) == 40


def test_metrics_count_events_and_runs(
    settings_override: Callable[..., Settings], tmp_path: Path
) -> None:
    metrics = Metrics(settings_override().observability)
    log = AuditLog(tmp_path / "a.jsonl", "r1", on_event=metrics.observe_event)
    _record(log, "mapper", usd=0.5, latency_ms=1500.0)
    _record(log, "mapper", cached=True)
    metrics.run_finished("done")
    text = metrics.render().decode()
    assert 'vg_steps_total{cached="false",stage="mapper"} 1.0' in text
    assert 'vg_steps_total{cached="true",stage="mapper"} 1.0' in text
    assert 'vg_tokens_total{direction="in"} 6.0' in text
    assert "vg_cost_usd_total 0.5" in text
    assert 'vg_runs_total{status="done"} 1.0' in text
    assert 'vg_step_latency_seconds_count{stage="mapper"} 2.0' in text


def test_two_metrics_objects_do_not_share_state(
    settings_override: Callable[..., Settings],
) -> None:
    a, b = (Metrics(settings_override().observability) for _ in range(2))
    a.run_finished("done")
    assert b'vg_runs_total{status="done"}' not in b.render()
