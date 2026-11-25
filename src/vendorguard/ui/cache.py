"""A tiny per-session cache: lists are re-fetched at most every ``ttl_s`` seconds.

``state`` is ``st.session_state`` or any dict-like object (Streamlit's proxy is not a
MutableMapping, so it is typed loosely)."""

from collections.abc import Callable
from typing import Any


def fresh[T](
    state: Any,
    key: str,
    ttl_s: float,
    loader: Callable[[], T],
    clock: Callable[[], float],
) -> T:
    """The cached value of ``key`` if it is younger than ``ttl_s``, else ``loader()`` (stored)."""
    now = clock()
    cached = state.get(key)
    if cached is not None and now - cached[0] < ttl_s:
        return cached[1]  # type: ignore[no-any-return]
    value = loader()
    state[key] = (now, value)
    return value


def forget_prefix(state: Any, prefix: str) -> None:
    """Drop every cached value whose key starts with ``prefix`` (after a change on the server)."""
    for key in [k for k in state if isinstance(k, str) and k.startswith(prefix)]:
        del state[key]


LISTS = "list:"  # the prefix of every cached list (vendors, history per vendor)


__all__ = ["LISTS", "forget_prefix", "fresh"]
