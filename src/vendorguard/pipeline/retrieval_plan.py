"""Retrieve the evidence of every control once, before the worker threads start."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from vendorguard.config import Settings
from vendorguard.errors import EmbeddingError
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.embedder import Embedder
from vendorguard.models.control import ControlSet
from vendorguard.models.evidence import Chunk, ScoredChunk
from vendorguard.retrieval.hybrid import HybridRetriever
from vendorguard.retrieval.tokenizer import Tokenizer
from vendorguard.utils.hashing import hash_obj

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlEvidence:
    """``top`` (the Mapper's chunks) is the first ``top_k`` of ``wide`` (the Reviewer's chunks)."""

    top: list[ScoredChunk]
    wide: list[ScoredChunk]


def _retrieve_all(
    chunks: Sequence[Chunk], controls: ControlSet, embedder: Embedder | None, settings: Settings
) -> dict[str, ControlEvidence]:
    retriever = HybridRetriever(
        chunks, Tokenizer(settings.retrieval.stop_words), embedder, settings.retrieval
    )
    top_k = settings.retrieval.top_k
    wide_k = top_k + settings.pipeline.review_extra_chunks
    plan: dict[str, ControlEvidence] = {}
    for control in controls.controls:
        wide = retriever.for_control(control, wide_k)
        plan[control.id] = ControlEvidence(top=wide[:top_k], wide=wide)
    return plan


def plan_evidence(
    chunks: Sequence[Chunk],
    controls: ControlSet,
    embedder: Embedder | None,
    settings: Settings,
    audit: AuditSink,
) -> dict[str, ControlEvidence]:
    """Evidence per control ID. If the embedder fails, ALL controls are redone with BM25 only
    (so one run never mixes scoring modes) and a ``retrieval_fallback`` event is recorded."""
    try:
        return _retrieve_all(chunks, controls, embedder, settings)
    except EmbeddingError as exc:
        log.warning("embedder failed (%s): retrieval continues with BM25 only", type(exc).__name__)
        audit.record(
            stage="retrieval_fallback",
            actor="python/bm25",
            input_hash=hash_obj(settings.embeddings.provider),
            output_hash=hash_obj(type(exc).__name__),
            tokens_in=0,
            tokens_out=0,
            usd=0.0,
            latency_ms=0.0,
            cached=False,
        )
        return _retrieve_all(chunks, controls, None, settings)


__all__ = ["ControlEvidence", "plan_evidence"]
