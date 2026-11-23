"""Live Jev check (marker ``jev``): one tiny real call. Needs VG_DECISION__JEV__API_KEY."""

import os

import pytest

from vendorguard.config import get_settings
from vendorguard.providers.decide.jev_client import JevClient

pytestmark = pytest.mark.jev


def test_jev_answers_a_yes_no_question() -> None:
    if not os.environ.get("VG_DECISION__JEV__API_KEY"):
        pytest.skip("VG_DECISION__JEV__API_KEY is not set")
    s = get_settings()
    client = JevClient(s.decision.jev, s.llm)
    questions = {"ok": {"type": "noul", "instructions": "Is the sky blue on a clear day?"}}
    answers, usage = client.ask({"note": "Daytime, no clouds."}, questions)
    assert 0.0 <= answers["ok"] <= 1.0 and usage.tokens_in > 0
