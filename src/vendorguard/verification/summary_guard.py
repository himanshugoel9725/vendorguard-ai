"""Number guard: an executive summary may only contain facts that are in the structured result."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

CONTROL_ID = re.compile(r"\b[A-Z]{2,5}-\d{2,3}\b")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _walk(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(key)
            yield from _walk(item)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def _facts_numbers_and_ids(facts: Mapping[str, Any]) -> tuple[set[float], set[str]]:
    numbers: set[float] = set()
    ids: set[str] = set()
    for leaf in _walk(facts):
        if isinstance(leaf, bool):
            continue
        if isinstance(leaf, int | float):
            numbers.add(float(leaf))
        elif isinstance(leaf, str):
            ids.update(CONTROL_ID.findall(leaf))
            numbers.update(float(n) for n in NUMBER.findall(CONTROL_ID.sub(" ", leaf)))
    counts = facts.get("counts")
    if isinstance(counts, Mapping):
        numbers.add(float(sum(v for v in counts.values() if isinstance(v, int | float))))
    return numbers, ids


def check_summary(summary: str, facts: Mapping[str, Any], max_words: int) -> list[str]:
    """The problems found in ``summary`` (empty list = acceptable). Messages never contain
    the offending text beyond the number or control ID itself.

    Every control ID must be in the facts, every number must equal a number in the facts
    exactly (no rounding) or the total of the status counts, and the text must not exceed
    ``max_words``. The vendor name is removed first so digits inside it do not count. Numbers
    written as words are not checked (known limit).
    """
    problems: list[str] = []
    words = len(summary.split())
    if words > max_words:
        problems.append(f"the summary has {words} words, more than the limit of {max_words}")
    allowed_numbers, allowed_ids = _facts_numbers_and_ids(facts)
    text = (
        summary.replace(str(facts.get("vendor_name", "")), " ")
        if facts.get("vendor_name")
        else summary
    )
    for control_id in sorted(set(CONTROL_ID.findall(text)) - allowed_ids):
        problems.append(f"control {control_id} is not in the result")
    bare = CONTROL_ID.sub(" ", text)
    for raw in sorted(set(NUMBER.findall(bare))):
        if float(raw) not in allowed_numbers:
            problems.append(f"the number {raw} is not in the result")
    return problems


__all__ = ["check_summary"]
