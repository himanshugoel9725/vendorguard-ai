"""Mock Reporter and Ask agents: the shared fallback templates over the facts they are given."""

from typing import Any

from vendorguard.reporting.fallback_answer import fallback_answer
from vendorguard.reporting.fallback_summary import fallback_summary


def summary_text(facts: dict[str, Any]) -> str:
    """The executive summary: the shared fallback template (only numbers from ``facts``)."""
    return fallback_summary(facts)


def answer(question: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """An ``AskOutput`` as a dict: the shared fallback answer. ``runs`` are newest first."""
    return fallback_answer(question, runs)


__all__ = ["answer", "summary_text"]
