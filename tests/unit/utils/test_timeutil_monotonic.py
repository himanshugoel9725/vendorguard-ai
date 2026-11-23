"""monotonic_s: a float clock that never goes backwards."""

from vendorguard.utils.timeutil import monotonic_s


def test_monotonic_s_is_float_and_non_decreasing_over_1000_calls() -> None:
    values = [monotonic_s() for _ in range(1000)]
    assert all(isinstance(v, float) for v in values)
    assert values == sorted(values)
