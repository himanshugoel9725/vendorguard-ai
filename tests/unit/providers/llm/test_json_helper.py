"""The shared parse-validate-repair helper."""

from collections.abc import Sequence
from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError

from vendorguard.errors import SchemaValidationError
from vendorguard.models.llm import ChatMessage, Usage
from vendorguard.providers.llm._json import (
    complete_with_repair,
    describe_problem,
    extract_json,
    repair_messages,
)


class Out(BaseModel):
    status: Literal["a", "b"]
    items: list[int]


GOOD = '{"status": "a", "items": [1, 2]}'
MSGS = [ChatMessage(role="user", content="q")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('  {"a": 1}\n', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```JSON {"a": 1} ```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('text ```json {"a": 1}```', 'text ```json {"a": 1}```'),  # only a whole-reply fence counts
    ],
)
def test_extract_json(raw: str, expected: str) -> None:
    assert extract_json(raw) == expected


def test_describe_problem_lists_paths_and_messages_without_values() -> None:
    with pytest.raises(ValidationError) as info:
        Out.model_validate({"status": "SECRET-VALUE", "items": ["x"]})
    text = describe_problem(info.value)
    assert "status:" in text and "items.0:" in text and "SECRET-VALUE" not in text
    assert text == describe_problem(info.value)  # stable order


def test_repair_messages_append_the_bad_reply_and_the_request() -> None:
    out = repair_messages(MSGS, "oops", "status: bad")
    assert out[:1] == MSGS and out[1] == ChatMessage(role="assistant", content="oops")
    assert out[2].role == "user" and "status: bad" in out[2].content and len(out) == 3


def _sender(replies: list[str]) -> tuple[list[list[ChatMessage]], object]:
    seen: list[list[ChatMessage]] = []
    queue = iter(replies)

    def send(conversation: Sequence[ChatMessage]) -> tuple[str, Usage]:
        seen.append(list(conversation))
        return next(queue), Usage(tokens_in=10, tokens_out=2)

    return seen, send


def test_valid_first_reply_makes_one_call() -> None:
    seen, send = _sender([GOOD])
    parsed, usage = complete_with_repair(send, MSGS, Out, 3)  # type: ignore[arg-type]
    assert parsed == Out(status="a", items=[1, 2]) and len(seen) == 1
    assert (usage.tokens_in, usage.tokens_out) == (10, 2)


def test_each_repair_restarts_from_the_original_messages_not_a_growing_chain() -> None:
    seen, send = _sender(["bad1", "bad2", GOOD])
    parsed, usage = complete_with_repair(send, MSGS, Out, 2)  # type: ignore[arg-type]
    assert parsed.status == "a" and usage.tokens_in == 30
    assert [len(c) for c in seen] == [1, 3, 3]
    assert seen[2][1].content == "bad2"  # the latest bad reply, not the first


def test_exhausted_repairs_raise_with_the_attempt_count_and_field_paths() -> None:
    _seen, send = _sender(['{"status": "z", "items": []}'] * 2)
    with pytest.raises(
        SchemaValidationError, match=r"Out: invalid output after 2 attempt\(s\): status:"
    ):
        complete_with_repair(send, MSGS, Out, 1)  # type: ignore[arg-type]


def test_zero_repair_attempts_never_re_asks() -> None:
    seen, send = _sender(["bad", GOOD])
    with pytest.raises(SchemaValidationError):
        complete_with_repair(send, MSGS, Out, 0)  # type: ignore[arg-type]
    assert len(seen) == 1
