"""Guard for the Ask agent: it may only name runs and controls that exist in the data it saw."""

import re
from collections.abc import Collection

from vendorguard.models.outputs import AskOutput
from vendorguard.verification.text_normalize import normalize_text

# After ``normalize_text`` (NFKC, casefold, dashes to ASCII): no word-boundary requirement on the
# left, so a made-up ID glued to letters ("xdat-01") is matched whole and then rejected as unknown.
CONTROL_ID = re.compile(r"[a-z]{2,5}-\d{2,3}(?!\d)")
RUN_ID = re.compile(r"run_[a-z0-9_-]+")


def check_answer(
    answer: AskOutput, run_ids: Collection[str], control_ids: Collection[str]
) -> list[str]:
    """The problems found in ``answer`` (empty list = acceptable). Messages hold only the
    offending ID (lower-case), never other text.

    Every cited ID and every ID written in the text must exist in the data the model was shown
    (compared case-insensitively), and every existing ID written in the text must be cited (the
    prompt demands both, and a reader relies on the cited lists). The guard checks IDs, not the
    truth of the sentences around them: that part is only as good as the model (ADR-018).
    """
    text = normalize_text(answer.text)
    known_runs = {r.casefold() for r in run_ids}
    known_controls = {c.casefold() for c in control_ids}
    mentioned_runs = {r.rstrip("_-") for r in RUN_ID.findall(text)}
    cited_runs = {r.casefold() for r in answer.cited_run_ids}
    mentioned_controls = set(CONTROL_ID.findall(RUN_ID.sub(" ", text)))  # run IDs are not controls
    cited_controls = {c.casefold() for c in answer.cited_control_ids}
    problems: list[str] = []
    for run in sorted(cited_runs | mentioned_runs):
        if run not in known_runs:
            problems.append(f"run {run} is not in the data")
    problems += [
        f"run {run} is written in the text but not cited"
        for run in sorted(mentioned_runs - cited_runs)
        if run in known_runs
    ]
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
