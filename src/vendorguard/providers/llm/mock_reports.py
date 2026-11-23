"""Mock Reporter and Ask agents: fixed templates over the structured facts they are given."""

import re
from typing import Any

CONTROL_ID = re.compile(r"\b[A-Z]{3}-\d{2}\b")
_CHANGE_WORDS = ("change", "changed", "since", "diff", "differ", "improve", "worse", "new gap")
_OK = "met"


def summary_text(facts: dict[str, Any]) -> str:
    """The executive summary: only numbers and control IDs that come from ``facts``."""
    counts: dict[str, int] = facts["counts"]
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


def _gaps(findings: dict[str, str]) -> list[str]:
    return sorted(c for c, status in findings.items() if status != _OK)


def answer(question: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
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
    if len(runs) > 1 and any(w in question.lower() for w in _CHANGE_WORDS):
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


__all__ = ["answer", "summary_text"]
