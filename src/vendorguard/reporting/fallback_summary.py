"""The deterministic executive summary: a template over the structured result, no model.

Used when the number guard rejects the Reporter Agent's text (or the model fails) and as the
mock LLM's answer, so both can never differ.
"""

from collections.abc import Mapping
from typing import Any


def fallback_summary(facts: Mapping[str, Any]) -> str:
    """Only numbers and control IDs that come from ``facts``: ``vendor_name``, ``overall``,
    ``band``, ``counts`` {status: n} and ``gaps`` [control IDs]."""
    counts: Mapping[str, int] = facts["counts"]
    total = sum(counts.values())
    text = (
        f"{facts['vendor_name']}: the overall residual risk score is {facts['overall']:g} "
        f"({facts['band']}). Of {total} controls, {counts.get('met', 0)} are met, "
        f"{counts.get('partial', 0)} partially met, {counts.get('not_met', 0)} not met, "
        f"{counts.get('no_evidence', 0)} without evidence and "
        f"{counts.get('needs_human_review', 0)} awaiting human review."
    )
    gaps: list[str] = sorted(facts.get("gaps", []))
    return text + (f" Open gaps: {', '.join(gaps)}." if gaps else " There are no open gaps.")


__all__ = ["fallback_summary"]
