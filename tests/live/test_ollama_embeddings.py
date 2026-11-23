"""Live check of the Ollama embedder against a running local server (skipped by default)."""

import math
from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.providers.embed.ollama import OllamaEmbedder

pytestmark = pytest.mark.ollama


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_real_embeddings_have_one_dimension_and_make_semantic_sense(
    settings_override: Callable[..., Settings],
) -> None:
    embedder = OllamaEmbedder(settings_override().embeddings)
    docs = embedder.embed_documents(
        [
            "Multi-factor authentication is enforced for all staff.",
            "Backups are encrypted and stored offsite.",
            "Employees can join running and chess clubs.",
        ]
    )
    assert len({len(v) for v in docs}) == 1 and len(docs[0]) > 100
    query = embedder.embed_query("Is MFA required for employees?")
    scores = [_cosine(query, d) for d in docs]
    assert scores[0] == max(scores)
    assert embedder.embed_documents(["same text"]) == embedder.embed_documents(["same text"])
