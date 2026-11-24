"""Citation checker: every quote the model returns must exist in the chunk it names."""

from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher

from pydantic import Field

from vendorguard.config_models.scoring import VerificationSettings
from vendorguard.models._base import ContractModel
from vendorguard.models.evidence import Chunk, Citation, DraftCitation
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.keyword_reading import split_sentences
from vendorguard.verification.text_normalize import normalize_text

SIMILARITY_DIGITS = 4


class CitationReport(ContractModel):
    """Checked citations plus the reasons (no quote text) the finding failed, if it did."""

    citations: list[Citation]
    ok: bool
    problems: list[str] = Field(default_factory=list)


def best_window(source: str, quote: str) -> tuple[float, str]:
    """(score, source window): 1.0 and the quote for a substring, else the difflib ratio
    against the best-aligned source window and that window's text."""
    if not quote:
        return 0.0, ""
    if quote in source:
        return 1.0, quote
    blocks = [
        b
        for b in SequenceMatcher(None, source, quote, autojunk=False).get_matching_blocks()
        if b.size
    ]
    if not blocks:
        return 0.0, ""
    first, last = blocks[0], blocks[-1]
    start = max(0, first.a - first.b)
    end = min(len(source), last.a + last.size + (len(quote) - last.b - last.size))
    window = source[start:end]
    return SequenceMatcher(None, window, quote, autojunk=False).ratio(), window


def best_window_similarity(source: str, quote: str) -> float:
    """1.0 for a substring, else the difflib ratio against the best-aligned source window."""
    return best_window(source, quote)[0]


class CitationChecker:
    """Deterministic check of quotes against the retrieved chunks; no model involved."""

    def __init__(self, settings: VerificationSettings) -> None:
        self._min_similarity = settings.citation_min_similarity
        self._max_quote_chars = settings.max_quote_chars
        self._required = set(settings.require_citation_for)

    def check_one(self, citation: DraftCitation, chunks: Mapping[str, Chunk]) -> Citation:
        """Check one quote against the chunk it names.

        A model often attaches a correct quote to the wrong chunk ID. If the quote is not in the
        named chunk but is verbatim (or fuzzily, see ``citation_min_similarity``) in another
        retrieved chunk, the citation is moved there (``relocated=True``): the quote is still
        verified against real source text. A fuzzy match keeps the SOURCE words, never the model's.
        """
        named = chunks.get(citation.chunk_id)
        if len(citation.quote) > self._max_quote_chars:
            return self._invalid(citation, named, 0.0)
        quote = normalize_text(citation.quote)
        named_score = 0.0
        if named is not None:
            named_score, window = best_window(normalize_text(named.text), quote)
            if named_score >= self._min_similarity:
                return self._valid(citation, named, named_score, window, relocated=False)
        found: tuple[float, str, Chunk] | None = None
        for chunk in sorted(chunks.values(), key=lambda c: c.chunk_id):
            if chunk is named:
                continue
            score, window = best_window(normalize_text(chunk.text), quote)
            if score >= self._min_similarity and (found is None or score > found[0]):
                found = (score, window, chunk)
        if found is None:
            return self._invalid(citation, named, named_score)
        return self._valid(citation, found[2], found[0], found[1], relocated=True)

    @staticmethod
    def _valid(
        citation: DraftCitation, chunk: Chunk, score: float, window: str, *, relocated: bool
    ) -> Citation:
        data = citation.model_dump()
        data["chunk_id"] = chunk.chunk_id
        if score < 1.0 and window:
            # A fuzzy match keeps the SOURCE words, never the model's: the original sentence
            # (with its case and punctuation) if the window lies inside one, else the window.
            data["quote"] = next(
                (
                    sentence
                    for sentence in split_sentences(chunk.text)
                    if window in normalize_text(sentence)
                ),
                window,
            )
        return Citation(
            **data,
            doc_id=chunk.doc_id,
            page=chunk.page,
            valid=True,
            similarity=round(score, SIMILARITY_DIGITS),
            relocated=relocated,
        )

    @staticmethod
    def _invalid(citation: DraftCitation, chunk: Chunk | None, score: float) -> Citation:
        return Citation(
            **citation.model_dump(),
            doc_id=chunk.doc_id if chunk else None,
            page=chunk.page if chunk else None,
            valid=False,
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


__all__ = ["CitationChecker", "CitationReport", "best_window", "best_window_similarity"]
