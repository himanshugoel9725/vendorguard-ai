"""plan_evidence: one retrieval per control, with an all-or-nothing BM25 fallback."""

from collections.abc import Callable, Sequence
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.errors import EmbeddingError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control, ControlSet
from vendorguard.models.evidence import Chunk
from vendorguard.pipeline.retrieval_plan import ControlEvidence, plan_evidence
from vendorguard.utils.timeutil import utcnow

Make = Callable[..., Settings]

TEXTS = [
    "Multi-factor authentication is enforced for administrators and staff accounts.",
    "Access reviews of user accounts happen every quarter by the security team.",
    "Backups are encrypted and restore tests run each quarter.",
    "Incident response procedures are tested annually with the security team.",
    "Staff accounts are removed on the day of departure after access reviews.",
    "Vulnerability scans run weekly and critical patches ship within seven days.",
    "Encryption of data at rest uses AES-256 for backups and databases.",
]


def _chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"d:p001:c{i:03d}", doc_id="d", page=1, text=t, char_start=0, char_end=len(t)
        )
        for i, t in enumerate(TEXTS)
    ]


def _control(cid: str, domain: str, kw: list[str]) -> Control:
    return Control(
        id=cid, title=f"Title {cid}", domain=domain, criticality="high", iso27001=[], nist_csf=[],
        requirement="Staff accounts and access are managed.", met_criteria="Done.", keywords=kw,
    )  # fmt: skip


CONTROLS = ControlSet(
    version="1", name="t", domains={"IAM": "Access", "BCP": "Backup"},
    controls=[
        _control("IAM-01", "IAM", ["accounts", "access", "MFA"]),
        _control("BCP-01", "BCP", ["backups", "restore", "encrypted"]),
    ],
)  # fmt: skip


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), **fields)
        self.events.append(e)
        return e


class FakeEmbedder:
    """Deterministic vectors from letter counts; optionally fails on the Nth query."""

    def __init__(self, fail_docs: bool = False, fail_query_at: int | None = None) -> None:
        self.fail_docs, self.fail_query_at, self.queries = fail_docs, fail_query_at, 0

    @staticmethod
    def _vec(text: str) -> list[float]:
        return [float(text.lower().count(c)) + 0.1 for c in "aeiost"]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail_docs:
            raise EmbeddingError("down")
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries += 1
        if self.fail_query_at is not None and self.queries >= self.fail_query_at:
            raise EmbeddingError("down")
        return self._vec(text)


@pytest.fixture
def s(settings_override: Make) -> Settings:
    return settings_override()


def test_top_is_the_first_top_k_of_wide(s: Settings) -> None:
    audit = FakeAudit()
    plan = plan_evidence(_chunks(), CONTROLS, None, s, audit)
    assert set(plan) == {"IAM-01", "BCP-01"}
    for ev in plan.values():
        assert isinstance(ev, ControlEvidence)
        assert ev.top == ev.wide[: s.retrieval.top_k]
        assert len(ev.top) <= s.retrieval.top_k
        assert len(ev.wide) <= s.retrieval.top_k + s.pipeline.review_extra_chunks
    assert any(len(ev.wide) > len(ev.top) for ev in plan.values())
    assert audit.events == []


def test_wide_size_follows_settings(settings_override: Make) -> None:
    s = settings_override(
        retrieval={"top_k": 1, "min_score": 0.0}, pipeline={"review_extra_chunks": 3}
    )
    ev = plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit())["IAM-01"]
    assert len(ev.top) == 1 and len(ev.wide) == 4


def test_zero_extra_chunks_makes_top_equal_wide(settings_override: Make) -> None:
    s = settings_override(pipeline={"review_extra_chunks": 0})
    for ev in plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit()).values():
        assert ev.top == ev.wide


def test_ranking_prefers_the_relevant_chunk(s: Settings) -> None:
    plan = plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit())
    assert plan["BCP-01"].top[0].chunk.chunk_id == "d:p001:c002"


def test_deterministic(s: Settings) -> None:
    a = plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit())
    b = plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit())
    assert a == b


def test_no_chunks_gives_empty_evidence(s: Settings) -> None:
    plan = plan_evidence([], CONTROLS, None, s, FakeAudit())
    assert all(ev.top == [] and ev.wide == [] for ev in plan.values())


def test_a_working_embedder_is_used_without_audit_event(s: Settings) -> None:
    audit = FakeAudit()
    emb = FakeEmbedder()
    plan = plan_evidence(_chunks(), CONTROLS, emb, s, audit)
    assert emb.queries == 2 and audit.events == [] and len(plan) == 2


def test_embedder_failure_at_indexing_falls_back_to_bm25(s: Settings) -> None:
    audit = FakeAudit()
    plan = plan_evidence(_chunks(), CONTROLS, FakeEmbedder(fail_docs=True), s, audit)
    assert plan == plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit())
    assert [e.stage for e in audit.events] == ["retrieval_fallback"]
    assert audit.events[0].actor == "python/bm25"


def test_embedder_failure_midway_redoes_all_controls_with_bm25(s: Settings) -> None:
    audit = FakeAudit()
    plan = plan_evidence(_chunks(), CONTROLS, FakeEmbedder(fail_query_at=2), s, audit)
    assert plan == plan_evidence(_chunks(), CONTROLS, None, s, FakeAudit())
    assert [e.stage for e in audit.events] == ["retrieval_fallback"]
    # no scoring mode mix: no vector signal on any hit
    assert all(h.vector is None for ev in plan.values() for h in ev.wide)


def test_fallback_event_is_deterministic_and_has_no_error_text(s: Settings) -> None:
    a, b = FakeAudit(), FakeAudit()
    plan_evidence(_chunks(), CONTROLS, FakeEmbedder(fail_docs=True), s, a)
    plan_evidence(_chunks(), CONTROLS, FakeEmbedder(fail_docs=True), s, b)
    assert a.events[0].output_hash == b.events[0].output_hash
    assert "down" not in a.events[0].model_dump_json()
