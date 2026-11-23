"""The interfaces stay exactly as in docs/PLAN.md section 6 (a change needs an ADR)."""

import inspect
from typing import Any

import pytest

from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.cache import CacheBackend
from vendorguard.interfaces.decider import Decider
from vendorguard.interfaces.embedder import Embedder
from vendorguard.interfaces.llm import LLMClient
from vendorguard.interfaces.memory import MemoryAssistant, MemoryStore


def _members(protocol: type) -> tuple[set[str], set[str]]:
    methods = {
        n for n, v in vars(protocol).items() if inspect.isfunction(v) and not n.startswith("_")
    }
    attrs = set(getattr(protocol, "__annotations__", {}))
    return methods, attrs


@pytest.mark.parametrize(
    ("protocol", "methods", "attrs"),
    [
        (LLMClient, {"complete_json"}, {"provider", "model"}),
        (Embedder, {"embed_documents", "embed_query"}, {"model"}),
        (Decider, {"triage", "verify"}, {"name"}),
        (
            MemoryStore,
            {
                "save_assessment",
                "get_assessment",
                "latest_assessment",
                "list_assessments",
                "list_vendors",
            },
            set(),
        ),
        (MemoryAssistant, {"ask"}, set()),
        (CacheBackend, {"get", "put"}, set()),
        (AuditSink, {"record"}, set()),
    ],
)
def test_protocol_members_match_the_plan(
    protocol: type, methods: set[str], attrs: set[str]
) -> None:
    assert _members(protocol) == (methods, attrs)


def test_complete_json_signature_matches_the_plan() -> None:
    sig = inspect.signature(LLMClient.complete_json)
    assert list(sig.parameters) == ["self", "messages", "output_model", "purpose", "hints"]
    assert sig.parameters["purpose"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["hints"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["hints"].default is None


def test_decider_and_memory_signatures_match_the_plan() -> None:
    assert list(inspect.signature(Decider.triage).parameters) == ["self", "control", "evidence"]
    assert list(inspect.signature(Decider.verify).parameters) == [
        "self",
        "control",
        "draft",
        "evidence",
    ]
    latest = inspect.signature(MemoryStore.latest_assessment)
    assert latest.parameters["exclude_run_id"].kind is inspect.Parameter.KEYWORD_ONLY
    put = inspect.signature(CacheBackend.put)
    assert put.parameters["purpose"].kind is inspect.Parameter.KEYWORD_ONLY


def test_a_plain_class_can_implement_a_protocol_without_inheriting() -> None:
    class Fake:
        provider = "fake"
        model = "m"

        def complete_json(
            self, messages: Any, output_model: Any, *, purpose: str, hints: Any = None
        ) -> Any:
            return None

    client: LLMClient = Fake()  # structural typing: no inheritance needed
    assert client.provider == "fake"


def test_audit_sink_record_is_keyword_only_with_the_documented_fields() -> None:
    sig = inspect.signature(AuditSink.record)
    names = list(sig.parameters)
    assert names[0] == "self" and all(
        sig.parameters[n].kind is inspect.Parameter.KEYWORD_ONLY for n in names[1:]
    )
    assert set(names[1:]) == {
        "stage", "actor", "input_hash", "output_hash", "tokens_in", "tokens_out", "usd",
        "latency_ms", "cached", "control_id", "decision",
    }  # fmt: skip
    assert (
        sig.parameters["control_id"].default is None and sig.parameters["decision"].default is None
    )
