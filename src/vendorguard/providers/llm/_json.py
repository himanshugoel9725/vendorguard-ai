"""Shared by the LLM providers: parse model output as JSON, validate it, and re-ask on failure."""

import re
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ValidationError

from vendorguard.errors import SchemaValidationError
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.utils.timeutil import monotonic_s

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> str:
    """The reply without surrounding whitespace or a Markdown code fence."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1) if match else stripped


def describe_problem(exc: ValidationError) -> str:
    """Field paths and messages of a validation error (never the offending values)."""
    lines = [
        f"{'.'.join(str(p) for p in err['loc']) or 'output'}: {err['msg']}" for err in exc.errors()
    ]
    return "; ".join(sorted(lines))


def repair_messages(
    messages: Sequence[ChatMessage], bad_output: str, problem: str
) -> list[ChatMessage]:
    """The conversation plus the invalid reply and a request to correct it."""
    return [
        *messages,
        ChatMessage(role="assistant", content=bad_output),
        ChatMessage(
            role="user",
            content=(
                f"Your previous reply was not valid ({problem}). "
                "Reply again with only the JSON object that matches the schema."
            ),
        ),
    ]


def complete_with_repair[T: BaseModel](
    send: Callable[[Sequence[ChatMessage]], tuple[str, Usage]],
    messages: Sequence[ChatMessage],
    output_model: type[T],
    repair_attempts: int,
) -> tuple[T, Usage]:
    """Call ``send`` and validate the reply; re-ask up to ``repair_attempts`` times when invalid.

    Returns the parsed output and the tokens of every call. Raises SchemaValidationError when the
    last reply is still invalid.
    """
    conversation = list(messages)
    tokens_in = tokens_out = 0
    for attempt in range(repair_attempts + 1):
        text, usage = send(conversation)
        tokens_in += usage.tokens_in
        tokens_out += usage.tokens_out
        try:
            parsed = output_model.model_validate_json(extract_json(text))
        except ValidationError as exc:
            problem = describe_problem(exc)
            if attempt == repair_attempts:
                raise SchemaValidationError(
                    f"{output_model.__name__}: invalid output after {attempt + 1} attempt(s): "
                    f"{problem}"
                ) from exc
            conversation = repair_messages(messages, text, problem)
        else:
            return parsed, Usage(tokens_in=tokens_in, tokens_out=tokens_out)
    raise AssertionError("unreachable")  # the loop always returns or raises  # noqa: S101


def run_chat[T: BaseModel](
    send: Callable[[Sequence[ChatMessage]], tuple[str, Usage]],
    messages: Sequence[ChatMessage],
    output_model: type[T],
    *,
    provider: str,
    model: str,
    repair_attempts: int,
) -> LLMResult[T]:
    """``complete_with_repair`` wrapped into an ``LLMResult`` with the call's latency."""
    started = monotonic_s()
    parsed, usage = complete_with_repair(send, messages, output_model, repair_attempts)
    return LLMResult[T](
        parsed=parsed,
        usage=usage,
        provider=provider,
        model=model,
        latency_ms=round((monotonic_s() - started) * 1000, 3),
    )


__all__ = [
    "complete_with_repair",
    "describe_problem",
    "extract_json",
    "repair_messages",
    "run_chat",
]
