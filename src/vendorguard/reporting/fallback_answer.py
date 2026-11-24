"""The deterministic answer of the Ask agent: a template over the stored runs, no model.

Used when the guard rejects the model's answer (or the model fails) and as the mock LLM's
answer, so both can never differ (the same pattern as ``fallback_summary``).
"""

import re
from typing import Any

from vendorguard.models.finding import DraftStatus

CONTROL_ID = re.compile(r"\b[A-Z]{3}-\d{2}\b")
_CHANGE_WORDS = re.compile(
    r"\b(?:change[sd]?|since|diff|differ(?:s|ed|ent|ences?)?|improv\w*|worse|new gaps?)\b",
    re.IGNORECASE,
)
_OK = DraftStatus.MET.value


def _gaps(findings: dict[str, str]) -> list[str]:
    return sorted(c for c, status in findings.items() if status != _OK)


def fallback_answer(question: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """An ``AskOutput`` as a dict. ``runs`` are the vendor's assessments, newest first."""
    if not runs:
        return {
            "text": "No assessments are stored for this vendor.",
            "cited_run_ids": [],
            "cited_control_ids": [],
        }
    latest = runs[0]
    findings: dict[str, str] = latest["findings"]
    asked = sorted({c for c in CONTROL_ID.findall(question) if c in findings})
    if len(runs) > 1 and _CHANGE_WORDS.search(question):
        previous = runs[1]
        before, after = set(_gaps(previous["findings"])), set(_gaps(findings))
        new, resolved = sorted(after - before), sorted(before - after)
        text = (
            f"Between run {previous['run_id']} and run {latest['run_id']} the overall score "
            f"went from {previous['overall']:g} to {latest['overall']:g}. "
            f"New gaps: {', '.join(new) or 'none'}. Resolved gaps: {', '.join(resolved) or 'none'}."
        )
        return {
            "text": text,
            "cited_run_ids": [latest["run_id"], previous["run_id"]],
            "cited_control_ids": new + resolved,
        }
    if asked:
        text = " ".join(f"{c} is {findings[c]} in run {latest['run_id']}." for c in asked)
        return {"text": text, "cited_run_ids": [latest["run_id"]], "cited_control_ids": asked}
    gaps = _gaps(findings)
    text = (
        f"Latest run {latest['run_id']}: overall score {latest['overall']:g} ({latest['band']}). "
        f"Gaps: {', '.join(gaps) or 'none'}."
    )
    return {"text": text, "cited_run_ids": [latest["run_id"]], "cited_control_ids": gaps}


__all__ = ["fallback_answer"]
