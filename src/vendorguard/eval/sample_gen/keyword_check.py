"""Reference keyword reading of a composed sample: does the text say what the spec says?

This is the same logic the mock LLM (task 4.4) uses, so a clean result here means the keyword
baseline can reach the golden labels.
"""

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.eval.sample_gen.models import ComposedSample
from vendorguard.eval.specs import SampleState, VendorSpec
from vendorguard.models.control import ControlSet
from vendorguard.utils.keywords import matching_phrases
from vendorguard.verification.keyword_reading import read_status, signals, split_sentences


def read_state(sentence: str, rules: RuleDeciderSettings) -> SampleState:
    """The state a keyword reader infers from the first sentence that mentions a control."""
    return SampleState(read_status(sentence, rules).value)


def check_composed(
    composed: ComposedSample, spec: VendorSpec, controls: ControlSet, rules: RuleDeciderSettings
) -> list[str]:
    """Return every disagreement between the spec and a keyword reading of the document."""
    problems: list[str] = []
    for control in controls.controls:
        found: tuple[str, int] | None = None
        for page_no, page in enumerate(composed.pages, start=1):
            for block in page:
                for sentence in split_sentences(block.text):
                    hits = matching_phrases(sentence, control.keywords)
                    if hits and block.kind == "injection":
                        problems.append(f"{control.id}: the injection paragraph matches {hits}")
                    elif hits and found is None:
                        found = (sentence, page_no)
        expected = spec.controls[control.id]
        inferred = SampleState.MISSING if found is None else read_state(found[0], rules)
        if inferred is not expected:
            where = f" ({found[0]!r} on page {found[1]})" if found else ""
            problems.append(
                f"{control.id}: spec says {expected.value}, text reads {inferred.value}{where}"
            )
    return problems


__all__ = ["check_composed", "read_state", "signals", "split_sentences"]
