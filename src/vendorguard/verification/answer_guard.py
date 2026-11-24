"""Guard for the Ask agent: it may only name runs and controls that exist in the data it saw."""

import re
from collections.abc import Collection

from vendorguard.models.outputs import AskOutput

CONTROL_ID = re.compile(r"\b[A-Z]{2,5}-\d{2,3}\b", re.IGNORECASE)
RUN_ID = re.compile(r"\brun_[A-Za-z0-9_-]+")


def check_answer(
    answer: AskOutput, run_ids: Collection[str], control_ids: Collection[str]
) -> list[str]:
    """The problems found in ``answer`` (empty list = acceptable). Messages hold only the
    offending ID, never other text.

    Every cited ID and every ID written in the text must exist in the data the model was shown,
    and every ID written in the text must also be cited (the prompt demands both, and a reader
    relies on the cited lists). The guard checks IDs, not the truth of the sentences around
    them: that part is only as good as the model (known limit, see ADR-018).
    """
    known_runs, known_controls = set(run_ids), {c.upper() for c in control_ids}
    problems: list[str] = []
    mentioned_runs = {r.rstrip("_-") for r in RUN_ID.findall(answer.text)}
    for run in sorted(set(answer.cited_run_ids) | mentioned_runs):
        if run not in known_runs:
            problems.append(f"run {run} is not in the data")
    problems += [
        f"run {run} is written in the text but not cited"
        for run in sorted(mentioned_runs - set(answer.cited_run_ids))
        if run in known_runs
    ]
    mentioned_controls = {c.upper() for c in CONTROL_ID.findall(answer.text)}
    cited_controls = {c.upper() for c in answer.cited_control_ids}
    for control in sorted(cited_controls | mentioned_controls):
        if control not in known_controls:
            problems.append(f"control {control} is not in the data")
    problems += [
        f"control {control} is written in the text but not cited"
        for control in sorted(mentioned_controls - cited_controls)
        if control in known_controls
    ]
    return problems


__all__ = ["check_answer"]
