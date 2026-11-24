"""Live check of the Ask agent against a local Ollama model (skipped by default)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.agents.ask import AskAgent
from vendorguard.config import Settings
from vendorguard.observability.audit_log import AuditLog
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.providers.llm.ollama import OllamaLLM
from vendorguard.providers.memory.sqlite_store import SqliteMemoryStore
from vendorguard.utils.prompt_loader import PromptLoader

pytestmark = pytest.mark.ollama

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"


def test_what_changed_cites_only_existing_ids(
    settings_override: Callable[..., Settings], tmp_path: Path
) -> None:
    mock_settings = settings_override()  # the two runs come from the mock pipeline
    store = SqliteMemoryStore(tmp_path / "mem.db", 5.0)
    first = run_assessment(mock_settings, "nimbara-hr", [SAMPLES / "nimbara-hr.pdf"], memory=store)
    second = run_assessment(
        mock_settings, "nimbara-hr", [SAMPLES / "nimbara-hr-y2.pdf"], memory=store
    )
    live = settings_override(llm={"provider": "ollama"})
    agent = AskAgent(
        OllamaLLM(live.llm),
        PromptLoader(ROOT / "prompts", live.prompts),
        AuditLog(tmp_path / "ask.audit.jsonl", "ask"),
        CostTracker(live.cost),
        store,
        live.memory,
        live.reporting,
    )
    answer = agent.ask("nimbara-hr", "What changed for nimbara-hr?")
    store.close()
    stored_controls = {f.control_id for f in second.findings}
    assert answer.text
    assert set(answer.cited_run_ids) <= {first.run_id, second.run_id}
    assert set(answer.cited_control_ids) <= stored_controls
