"""CachedLLM: off / read_write / read_only, with hits and misses counted."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from vendorguard.errors import CacheMissError, LLMError
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.cache.jsonl_cache import JsonlCache
from vendorguard.providers.cache.sqlite_cache import SqliteCache
from vendorguard.providers.llm.cached import CachedLLM

MSGS = [ChatMessage(role="user", content="question")]


class Out(BaseModel):
    answer: str


class Other(BaseModel):
    answer: str
    extra: int = 0


class Inner:
    provider = "fake"
    model = "m1"

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[Any],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:
        self.calls += 1
        if self.fail:
            raise LLMError("boom")
        return LLMResult(
            parsed=output_model(answer=f"a{self.calls}"),
            usage=Usage(tokens_in=10, tokens_out=3),
            provider=self.provider,
            model=self.model,
            latency_ms=5.0,
        )


class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.purposes: list[str] = []

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        self.data[key] = value
        self.purposes.append(purpose)


Mode = Literal["off", "read_write", "read_only"]


def _llm(
    mode: Mode, cache: DictCache | None = None, **params: Any
) -> tuple[Inner, DictCache, CachedLLM]:
    inner, store = Inner(), cache if cache is not None else DictCache()
    return inner, store, CachedLLM(inner, store, mode, params or {"seed": 1})


def _ask(llm: CachedLLM, messages: Sequence[ChatMessage] = MSGS, **kw: Any) -> LLMResult[Out]:
    return llm.complete_json(messages, Out, purpose=kw.pop("purpose", "mapper"), **kw)


# --- read_write ----------------------------------------------------------------------------------


def test_read_write_records_a_miss_and_replays_the_hit() -> None:
    inner, store, llm = _llm("read_write")
    first = _ask(llm)
    assert (first.cached, first.parsed.answer, inner.calls) == (False, "a1", 1)
    assert (llm.hits, llm.misses) == (0, 1) and len(store.data) == 1
    second = _ask(llm)
    assert second.parsed == first.parsed and second.cached is True and inner.calls == 1
    assert (llm.hits, llm.misses) == (1, 1)


def test_a_replayed_result_is_free_and_keeps_provenance() -> None:
    _inner, _store, llm = _llm("read_write")
    first = _ask(llm)
    assert (first.usage.tokens_in, first.usage.tokens_out) == (10, 3) and first.latency_ms == 5.0
    hit = _ask(llm)
    assert (hit.usage.tokens_in, hit.usage.tokens_out) == (0, 0) and hit.latency_ms == 0.0
    assert (hit.provider, hit.model) == ("fake", "m1")


def test_the_entry_holds_the_answer_but_never_the_prompt() -> None:
    _inner, store, llm = _llm("read_write")
    _ask(llm, [ChatMessage(role="user", content="SECRET-DOC")])
    (entry,) = store.data.values()
    assert set(entry) == {"parsed", "usage", "provider", "model"}
    assert "SECRET-DOC" not in str(entry) and store.purposes == ["mapper"]


@pytest.mark.parametrize("change", ["messages", "purpose", "schema", "params", "hints", "model"])
def test_a_different_call_is_a_different_entry(change: str) -> None:
    inner, store, llm = _llm("read_write")
    _ask(llm)
    other: CachedLLM = llm
    if change == "params":
        other = CachedLLM(inner, store, "read_write", {"seed": 2})
    if change == "model":
        inner2 = Inner()
        inner2.model = "m2"
        other = CachedLLM(inner2, store, "read_write", {"seed": 1})
    if change == "schema":
        other.complete_json(MSGS, Other, purpose="mapper")
    elif change == "messages":
        _ask(other, [ChatMessage(role="user", content="different")])
    elif change == "purpose":
        _ask(other, purpose="reviewer")
    elif change == "hints":
        _ask(other, hints={"k": 1})
    else:
        _ask(other)
    assert len(store.data) == 2


def test_the_same_hints_replay() -> None:
    inner, _store, llm = _llm("read_write")
    _ask(llm, hints={"keywords": ["a"]})
    assert _ask(llm, hints={"keywords": ["a"]}).cached and inner.calls == 1


def test_a_failing_call_is_not_cached_and_not_hidden() -> None:
    inner, store, llm = _llm("read_write")
    inner.fail = True
    with pytest.raises(LLMError, match="boom"):
        _ask(llm)
    assert store.data == {} and llm.misses == 1
    inner.fail = False
    assert _ask(llm).cached is False and len(store.data) == 1


def test_a_damaged_entry_is_recomputed_and_repaired() -> None:
    inner, store, llm = _llm("read_write")
    _ask(llm)
    key = next(iter(store.data))
    for broken in ({}, {"parsed": {"nope": 1}}, {"parsed": "text"}):
        store.data[key] = broken
        assert _ask(llm).cached is False
        assert "parsed" in store.data[key] and store.data[key]["parsed"] == {
            "answer": f"a{inner.calls}"
        }


# --- read_only -----------------------------------------------------------------------------------


def test_read_only_replays_recorded_answers_and_never_calls_the_client() -> None:
    inner, store, writer = _llm("read_write")
    recorded = _ask(writer).parsed
    reader_inner = Inner()
    reader = CachedLLM(reader_inner, store, "read_only", {"seed": 1})
    assert _ask(reader).parsed == recorded and _ask(reader).cached
    assert reader_inner.calls == 0 and (reader.hits, reader.misses) == (2, 0)


def test_a_read_only_miss_raises_with_the_record_instruction() -> None:
    inner, store, llm = _llm("read_only")
    with pytest.raises(CacheMissError, match=r"'mapper' call.*run make record"):
        _ask(llm)
    assert inner.calls == 0 and store.data == {} and (llm.hits, llm.misses) == (0, 1)


def test_a_read_only_damaged_entry_is_a_miss() -> None:
    _inner, store, writer = _llm("read_write")
    _ask(writer)
    store.data[next(iter(store.data))] = {"parsed": {"bad": 1}}
    with pytest.raises(CacheMissError):
        _ask(CachedLLM(Inner(), store, "read_only", {"seed": 1}))


# --- off -----------------------------------------------------------------------------------------


def test_off_never_reads_or_writes_and_counts_nothing() -> None:
    inner, store, llm = _llm("off")
    store.data["pre"] = {"x": 1}
    results = [_ask(llm) for _ in range(3)]
    assert inner.calls == 3 and [r.cached for r in results] == [False] * 3
    assert [r.parsed.answer for r in results] == ["a1", "a2", "a3"]
    assert list(store.data) == ["pre"] and (llm.hits, llm.misses) == (0, 0)


def test_without_a_cache_every_mode_behaves_like_off() -> None:
    for mode in ("off", "read_write", "read_only"):
        inner = Inner()
        llm = CachedLLM(inner, None, mode, {})  # type: ignore[arg-type]
        _ask(llm)
        _ask(llm)
        assert inner.calls == 2 and (llm.hits, llm.misses) == (0, 0)


def test_provider_and_model_come_from_the_wrapped_client() -> None:
    _inner, _store, llm = _llm("off")
    assert (llm.provider, llm.model) == ("fake", "m1")


# --- real backends -------------------------------------------------------------------------------


def test_record_with_sqlite_and_replay_in_a_new_process_state(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    inner = Inner()
    first_cache = SqliteCache(db)
    recorded = _ask(CachedLLM(inner, first_cache, "read_write", {"seed": 1})).parsed
    first_cache.close()
    replay = CachedLLM(Inner(), SqliteCache(db), "read_only", {"seed": 1})
    assert _ask(replay).parsed == recorded and replay.hits == 1


def test_record_to_cassettes_and_replay_them_read_only(tmp_path: Path) -> None:
    folder = tmp_path / "cassettes"
    cache = JsonlCache(folder)
    recorded = _ask(CachedLLM(Inner(), cache, "read_write", {"seed": 1})).parsed
    cache.close()
    reader_inner = Inner()
    replay = CachedLLM(reader_inner, JsonlCache(folder), "read_only", {"seed": 1})
    assert _ask(replay).parsed == recorded and reader_inner.calls == 0
    assert (folder / "mapper.jsonl").read_text().count("\n") == 1
