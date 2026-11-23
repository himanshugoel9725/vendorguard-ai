"""Citation checker: every quote the model returns must exist in the chunk it names."""

from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher

from pydantic import Field

from vendorguard.config_models.scoring import VerificationSettings
from vendorguard.models._base import ContractModel
from vendorguard.models.evidence import Chunk, Citation, DraftCitation
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.text_normalize import normalize_text

SIMILARITY_DIGITS = 4


class CitationReport(ContractModel):
    """Checked citations plus the reasons (no quote text) the finding failed, if it did."""

    citations: list[Citation]
    ok: bool
    problems: list[str] = Field(default_factory=list)


def best_window_similarity(source: str, quote: str) -> float:
    """1.0 for a substring, else the difflib ratio against the best-aligned source window."""
    if not quote:
        return 0.0
    if quote in source:
        return 1.0
    blocks = [
        b
        for b in SequenceMatcher(None, source, quote, autojunk=False).get_matching_blocks()
        if b.size
    ]
    if not blocks:
        return 0.0
    first, last = blocks[0], blocks[-1]
    start = max(0, first.a - first.b)
    end = min(len(source), last.a + last.size + (len(quote) - last.b - last.size))
    return SequenceMatcher(None, source[start:end], quote, autojunk=False).ratio()


class CitationChecker:
    """Deterministic check of quotes against the retrieved chunks; no model involved."""

    def __init__(self, settings: VerificationSettings) -> None:
        self._min_similarity = settings.citation_min_similarity
        self._max_quote_chars = settings.max_quote_chars
        self._required = set(settings.require_citation_for)

    def check_one(self, citation: DraftCitation, chunks: Mapping[str, Chunk]) -> Citation:
        """Check one quote; an unknown chunk id or an over-long quote is invalid."""
        chunk = chunks.get(citation.chunk_id)
        if chunk is None:
            return Citation(**citation.model_dump(), valid=False, similarity=0.0)
        if len(citation.quote) > self._max_quote_chars:
            return Citation(
                **citation.model_dump(),
                doc_id=chunk.doc_id,
                page=chunk.page,
                valid=False,
                similarity=0.0,
            )
        score = best_window_similarity(normalize_text(chunk.text), normalize_text(citation.quote))
        return Citation(
            **citation.model_dump(),
            doc_id=chunk.doc_id,
            page=chunk.page,
            valid=score >= self._min_similarity,
            similarity=round(score, SIMILARITY_DIGITS),
        )

    def check(
        self,
        status: DraftStatus,
        citations: Sequence[DraftCitation],
        chunks: Sequence[Chunk],
    ) -> CitationReport:
        """Check all quotes of a draft. Fails if any quote is invalid, or if the status
        is in ``require_citation_for`` and no valid quote supports it."""
        by_id = {c.chunk_id: c for c in chunks}
        checked = [self.check_one(c, by_id) for c in citations]
        problems = [
            f"citation {i + 1} is not found in chunk {c.chunk_id}"
            for i, c in enumerate(checked)
            if not c.valid
        ]
        if status.value in self._required and not any(c.valid for c in checked):
            problems.append(f"status {status.value} requires at least one valid citation")
        return CitationReport(citations=checked, ok=not problems, problems=problems)


__all__ = ["CitationChecker", "CitationReport", "best_window_similarity"]
