"""The per-session refresh cache."""

from vendorguard.ui.cache import LISTS, forget_prefix, fresh


def test_loader_runs_only_when_the_value_is_stale() -> None:
    state: dict[str, object] = {}
    now = [100.0]
    calls: list[int] = []

    def loader() -> str:
        calls.append(1)
        return f"v{len(calls)}"

    assert fresh(state, "k", 15, loader, lambda: now[0]) == "v1"
    now[0] += 14
    assert fresh(state, "k", 15, loader, lambda: now[0]) == "v1" and len(calls) == 1
    now[0] += 2
    assert fresh(state, "k", 15, loader, lambda: now[0]) == "v2" and len(calls) == 2


def test_a_falsy_value_is_still_cached() -> None:
    state: dict[str, object] = {}
    calls: list[int] = []

    def loader() -> list[int]:
        calls.append(1)
        return []

    fresh(state, "k", 10, loader, lambda: 0.0)
    fresh(state, "k", 10, loader, lambda: 1.0)
    assert len(calls) == 1


def test_forget_prefix_drops_only_the_lists() -> None:
    state: dict[str, object] = {f"{LISTS}vendors": 1, f"{LISTS}history:v": 2, "result": 3, 5: 4}  # type: ignore[dict-item]
    forget_prefix(state, LISTS)
    assert set(state) == {"result", 5}
