"""Tests for vendorguard.utils.ids."""

import re

from vendorguard.utils.ids import make_run_id

SHAPE = re.compile(r"^run_[0-9a-f]{12}$")


def test_deterministic_shape_and_repeatable() -> None:
    a = make_run_id("v1", ["h1", "h2"], "fp", deterministic=True)
    assert SHAPE.match(a)
    assert a == make_run_id("v1", ["h1", "h2"], "fp", deterministic=True)


def test_deterministic_ignores_input_order() -> None:
    assert make_run_id("v", ["a", "b", "c"], "fp", deterministic=True) == make_run_id(
        "v", ["c", "a", "b"], "fp", deterministic=True
    )


def test_deterministic_accepts_iterator() -> None:
    assert make_run_id("v", iter(["a", "b"]), "fp", deterministic=True) == make_run_id(
        "v", ["b", "a"], "fp", deterministic=True
    )


def test_deterministic_changes_with_each_part() -> None:
    base = make_run_id("v", ["a", "b"], "fp", deterministic=True)
    assert make_run_id("w", ["a", "b"], "fp", deterministic=True) != base
    assert make_run_id("v", ["a", "x"], "fp", deterministic=True) != base
    assert make_run_id("v", ["a"], "fp", deterministic=True) != base
    assert make_run_id("v", ["a", "b"], "fp2", deterministic=True) != base


def test_empty_inputs() -> None:
    assert SHAPE.match(make_run_id("v", [], "fp", deterministic=True))


def test_random_ids_are_distinct_with_same_shape() -> None:
    ids = {make_run_id("v", ["a"], "fp", deterministic=False) for _ in range(5)}
    assert len(ids) == 5
    assert all(SHAPE.match(i) for i in ids)
