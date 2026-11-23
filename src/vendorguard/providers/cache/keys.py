"""Cache keys: a SHA-256 over everything that can change a model call's answer."""

from collections.abc import Mapping, Sequence
from typing import Any

from vendorguard.models.llm import ChatMessage
from vendorguard.utils.hashing import hash_obj, sha256_text


def llm_key(
    *,
    provider: str,
    model: str,
    purpose: str,
    messages: Sequence[ChatMessage],
    schema: Mapping[str, Any],
    params: Mapping[str, Any],
    hints: Mapping[str, Any] | None = None,
) -> str:
    """Key of one LLM call.

    The rendered messages are part of the key, so editing a prompt (or its inputs) changes the key
    and forces a re-recording. ``hints`` only matter to the mock provider but are included so two
    different mock questions can never share an entry.
    """
    return hash_obj(
        {
            "kind": "llm",
            "provider": provider,
            "model": model,
            "purpose": purpose,
            "messages": [m.model_dump() for m in messages],
            "schema_hash": hash_obj(schema),
            "params": dict(params),
            "hints": dict(hints) if hints else None,
        }
    )


def embedding_key(model: str, prefix: str, text: str) -> str:
    """Key of one embedding: model, task prefix and the SHA-256 of the text (never the text)."""
    return hash_obj(
        {"kind": "embedding", "model": model, "prefix": prefix, "text_sha256": sha256_text(text)}
    )


__all__ = ["embedding_key", "llm_key"]
