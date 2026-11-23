"""pick_index: deterministic, in range, input-sensitive and independent of PYTHONHASHSEED."""

import os
import subprocess
import sys

import pytest

from vendorguard.eval.sample_gen.variants import pick_index
from vendorguard.utils.hashing import sha256_text


def test_same_input_same_index() -> None:
    assert pick_index("v", "GOV-01", "met", 3) == pick_index("v", "GOV-01", "met", 3)


def test_known_fixed_input_matches_the_documented_formula() -> None:
    expected = int(sha256_text("brightdock|GOV-01|met")[:16], 16) % 3
    assert pick_index("brightdock", "GOV-01", "met", 3) == expected


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_index_in_range(count: int) -> None:
    for i in range(50):
        assert 0 <= pick_index(f"v{i}", "k", "met", count) < count


def test_count_one_is_always_zero() -> None:
    assert {pick_index(f"v{i}", f"k{i}", "s", 1) for i in range(30)} == {0}


@pytest.mark.parametrize("count", [0, -1])
def test_count_below_one_raises(count: int) -> None:
    with pytest.raises(ValueError):
        pick_index("v", "k", "s", count)


def test_each_argument_changes_the_result_across_many_inputs() -> None:
    base = {pick_index("v", f"k{i}", "met", 1000) for i in range(40)}
    assert len(base) > 1
    assert len({pick_index(f"v{i}", "k", "met", 1000) for i in range(40)}) > 1
    assert len({pick_index("v", "k", f"s{i}", 1000) for i in range(40)}) > 1


def test_unicode_inputs_work() -> None:
    assert 0 <= pick_index("vendeur-é", "clé", "état", 5) < 5


def test_stable_across_processes_and_hash_seeds() -> None:
    code = (
        "from vendorguard.eval.sample_gen.variants import pick_index;"
        "print(pick_index('nimbara-hr','IAM-02','partial',1000003))"
    )
    results = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        results.add(out.stdout.strip())
    assert results == {str(pick_index("nimbara-hr", "IAM-02", "partial", 1000003))}
