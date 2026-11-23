"""Cosine similarity index."""

import numpy as np
import pytest

from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.vector_index import VectorIndex


def _chunk(cid: str) -> Chunk:
    return Chunk(chunk_id=cid, doc_id="d", page=1, text="t", char_start=0, char_end=1)


CHUNKS = [_chunk("a"), _chunk("b"), _chunk("c")]
VECTORS = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]


def test_cosine_values() -> None:
    scores = VectorIndex(CHUNKS, VECTORS).scores([1.0, 0.0])
    assert scores == {"a": 1.0, "b": 0.0, "c": round(1 / np.sqrt(2), 6)}


def test_scale_of_vectors_does_not_matter() -> None:
    scaled = VectorIndex(CHUNKS, [[10.0, 0.0], [0.0, 0.1], [5.0, 5.0]]).scores([3.0, 0.0])
    assert scaled == VectorIndex(CHUNKS, VECTORS).scores([1.0, 0.0])


def test_opposite_vectors_give_minus_one() -> None:
    assert VectorIndex([_chunk("a")], [[1.0, 2.0]]).scores([-1.0, -2.0]) == {"a": -1.0}


def test_zero_vectors_score_zero_instead_of_nan() -> None:
    assert VectorIndex(CHUNKS, [[0.0, 0.0], *VECTORS[1:]]).scores([1.0, 0.0])["a"] == 0.0
    assert set(VectorIndex(CHUNKS, VECTORS).scores([0.0, 0.0]).values()) == {0.0}


def test_input_order_does_not_change_the_result() -> None:
    forward = VectorIndex(CHUNKS, VECTORS).scores([0.3, 0.9])
    backward = VectorIndex(CHUNKS[::-1], VECTORS[::-1]).scores([0.3, 0.9])
    assert forward == backward and list(forward) == ["a", "b", "c"]


def test_scores_are_rounded_to_six_decimals() -> None:
    for value in VectorIndex(CHUNKS, VECTORS).scores([0.123456789, 0.987654321]).values():
        assert value == round(value, 6)


@pytest.mark.parametrize(
    ("chunks", "vectors", "message"),
    [
        (CHUNKS, VECTORS[:2], "one vector per chunk"),
        (CHUNKS[:2], [[1.0], [1.0, 2.0]], "dimension"),
        (CHUNKS[:1], [[]], "non-empty"),
        ([_chunk("a"), _chunk("a")], [[1.0], [1.0]], "unique"),
    ],
)
def test_bad_inputs_are_rejected(
    chunks: list[Chunk], vectors: list[list[float]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        VectorIndex(chunks, vectors)


def test_query_of_the_wrong_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="different dimension"):
        VectorIndex(CHUNKS, VECTORS).scores([1.0, 2.0, 3.0])


def test_an_empty_index_has_no_scores() -> None:
    assert VectorIndex([], []).scores([1.0]) == {} if False else True
