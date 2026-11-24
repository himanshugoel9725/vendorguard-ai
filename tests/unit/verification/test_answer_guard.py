"""Answer guard: IDs cited or written must exist in the data; written IDs must be cited."""

import pytest

from vendorguard.models.outputs import AskOutput
from vendorguard.verification.answer_guard import check_answer

RUNS = ["run_aaa111", "run_bbb-222"]
CONTROLS = ["IAM-04", "OPS-02", "DAT-01"]


def _a(text: str, runs: list[str] | None = None, controls: list[str] | None = None) -> AskOutput:
    return AskOutput(text=text, cited_run_ids=runs or [], cited_control_ids=controls or [])


def test_good_answer_has_no_problems() -> None:
    a = _a("run_aaa111 closed IAM-04.", ["run_aaa111"], ["IAM-04"])
    assert check_answer(a, RUNS, CONTROLS) == []


def test_no_ids_anywhere_is_fine() -> None:
    assert check_answer(_a("The data cannot answer that."), RUNS, CONTROLS) == []


def test_cited_but_not_written_is_fine() -> None:
    assert check_answer(_a("Nothing changed.", ["run_aaa111"], ["IAM-04"]), RUNS, CONTROLS) == []


def test_known_run_written_but_not_cited() -> None:
    p = check_answer(_a("See run_aaa111."), RUNS, CONTROLS)
    assert p == ["run run_aaa111 is written in the text but not cited"]


def test_known_control_written_but_not_cited() -> None:
    p = check_answer(_a("OPS-02 is a new gap."), RUNS, CONTROLS)
    assert p == ["control ops-02 is written in the text but not cited"]


def test_unknown_ids_give_not_in_the_data_only() -> None:
    p = check_answer(_a("run_zzz and ZZZ-99 are odd."), RUNS, CONTROLS)
    assert p == ["run run_zzz is not in the data", "control zzz-99 is not in the data"]


def test_unknown_cited_ids() -> None:
    p = check_answer(_a("Fine.", ["run_x"], ["ZZZ-99"]), RUNS, CONTROLS)
    assert "run run_x is not in the data" in p and "control zzz-99 is not in the data" in p


def test_lowercase_control_in_text_is_normalised() -> None:
    assert check_answer(_a("iam-04 improved.", [], ["IAM-04"]), RUNS, CONTROLS) == []
    assert check_answer(_a("iam-04 improved."), RUNS, CONTROLS) == [
        "control iam-04 is written in the text but not cited"
    ]


def test_lowercase_cited_and_data_ids_match_case_insensitively() -> None:
    assert check_answer(_a("x", [], ["iam-04"]), RUNS, ["iam-04"]) == []


def test_trailing_punctuation_of_run_id_is_stripped() -> None:
    assert check_answer(_a("Look at run_aaa111_ now."), RUNS, CONTROLS) != []
    assert check_answer(_a("Look at run_aaa111_ now.", ["run_aaa111"]), RUNS, CONTROLS) == []


def test_hyphenated_run_id_is_matched_whole() -> None:
    assert check_answer(_a("run_b-x1 ok", ["run_b-x1"]), ["run_b-x1"], CONTROLS) == []


def test_a_run_id_that_ends_like_a_control_id_is_not_read_as_a_control() -> None:
    assert check_answer(_a("run_bbb-222 ok", ["run_bbb-222"]), ["run_bbb-222"], CONTROLS) == []


def test_messages_hold_only_the_id_and_are_sorted() -> None:
    p = check_answer(_a("secret words ZZZ-02 AAA-01 run_q."), RUNS, CONTROLS)
    assert p == [
        "run run_q is not in the data",
        "control aaa-01 is not in the data",
        "control zzz-02 is not in the data",
    ]
    assert not any("secret" in m for m in p)


@pytest.mark.parametrize("text", ["IAM-04", "iam-04", "Iam-04."])
def test_deterministic(text: str) -> None:
    a = _a(text)
    assert check_answer(a, RUNS, CONTROLS) == check_answer(a, RUNS, CONTROLS)


def test_unicode_and_empty_data() -> None:
    assert check_answer(_a("Übersicht – 100 % ok"), [], []) == []
    assert check_answer(_a("IAM-04", [], ["IAM-04"]), [], []) == [
        "control iam-04 is not in the data"
    ]


@pytest.mark.parametrize("dash", ["\u2013", "\u2014", "\u2011", "\u2212", "\u2010"])
def test_unicode_dash_forms_of_an_id_are_matched(dash: str) -> None:
    p = check_answer(_a(f"OPS{dash}02 is a gap."), RUNS, CONTROLS)
    assert p == ["control ops-02 is written in the text but not cited"]
    assert check_answer(_a(f"OPS{dash}02 is a gap.", [], ["OPS-02"]), RUNS, CONTROLS) == []


def test_uppercase_run_mention_is_seen() -> None:
    assert check_answer(_a("See RUN_ABC."), RUNS, CONTROLS) == ["run run_abc is not in the data"]
    assert check_answer(_a("See RUN_AAA111."), RUNS, CONTROLS) == [
        "run run_aaa111 is written in the text but not cited"
    ]
    assert check_answer(_a("See RUN_AAA111.", ["run_aaa111"]), RUNS, CONTROLS) == []


def test_glued_prefix_is_rejected_as_unknown() -> None:
    assert check_answer(_a("xDAT-01 is bad."), RUNS, CONTROLS) == [
        "control xdat-01 is not in the data"
    ]


def test_four_digit_number_is_not_a_control_id() -> None:
    assert check_answer(_a("DAT-0001 is odd."), RUNS, CONTROLS) == []


def test_cited_ids_in_other_case_count_as_cited() -> None:
    a = _a("run_aaa111 and DAT-01.", ["RUN_AAA111"], ["dat-01"])
    assert check_answer(a, RUNS, CONTROLS) == []
