"""Cache keys."""

import os
import subprocess
import sys

import pytest

from vendorguard.models.llm import ChatMessage
from vendorguard.providers.cache.keys import embedding_key, llm_key

MSGS = [ChatMessage(role="system", content="s"), ChatMessage(role="user", content="u SECRET-DOC")]
SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}
BASE = dict(
    provider="p", model="m", purpose="mapper", messages=MSGS, schema=SCHEMA, params={"seed": 1}
)


def _key(**changes: object) -> str:
    return llm_key(**{**BASE, **changes})  # type: ignore[arg-type]


def test_a_key_is_a_sha256_hex_and_repeatable() -> None:
    key = _key()
    assert len(key) == 64 and int(key, 16) >= 0 and key == _key()


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "q"},
        {"model": "n"},
        {"purpose": "reviewer"},
        {"messages": MSGS[:1]},
        {"messages": [MSGS[0], ChatMessage(role="user", content="other")]},
        {"messages": [MSGS[0], ChatMessage(role="assistant", content="u SECRET-DOC")]},
        {"schema": {**SCHEMA, "required": ["a"]}},
        {"params": {"seed": 2}},
        {"params": {"seed": 1, "temperature": 0.0}},
        {"hints": {"keywords": ["x"]}},
    ],
)
def test_every_input_changes_the_key(change: dict[str, object]) -> None:
    assert _key(**change) != _key()


def test_dict_order_does_not_matter_and_empty_hints_equal_no_hints() -> None:
    assert _key(params={"a": 1, "b": 2}) == _key(params={"b": 2, "a": 1})
    assert _key(schema={"x": 1, "y": 2}) == _key(schema={"y": 2, "x": 1})
    assert _key(hints=None) == _key(hints={})


def test_message_order_matters() -> None:
    assert _key(messages=MSGS[::-1]) != _key()


def test_a_key_never_contains_the_text() -> None:
    assert "SECRET-DOC" not in _key() and "mapper" not in _key()


def test_embedding_key_depends_on_model_prefix_and_text_only() -> None:
    k = embedding_key("m", "doc: ", "text")
    assert k == embedding_key("m", "doc: ", "text") and len(k) == 64
    assert len({k, embedding_key("n", "doc: ", "text"), embedding_key("m", "q: ", "text"),
                embedding_key("m", "doc: ", "texu")}) == 4  # fmt: skip
    assert "text" not in k


def test_llm_and_embedding_keys_never_collide() -> None:
    assert embedding_key("m", "p", "t") != _key()


def test_keys_are_identical_across_processes_and_hash_seeds() -> None:
    code = (
        "from vendorguard.models.llm import ChatMessage as C\n"
        "from vendorguard.providers.cache.keys import llm_key\n"
        "msgs = [C(role='user', content='u')]\n"
        "print(llm_key(provider='p', model='m', purpose='x', messages=msgs,\n"
        "              schema={'b': 1, 'a': {'z': 1, 'y': 2}}, params={'s': 1, 'a': 2},\n"
        "              hints={'k': ['b', 'a']}))\n"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("0", "1", "random")
    }
    assert len(outputs) == 1
