"""Ollama embedder, tested against a mocked HTTP server (no network)."""

import json
from collections.abc import Callable

import httpx
import pytest
import respx

from vendorguard.config import Settings
from vendorguard.errors import EmbeddingError
from vendorguard.providers.embed.ollama import OllamaEmbedder

URL = "http://localhost:11434/api/embed"


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Callable[..., OllamaEmbedder]:
    def build(**embeddings: object) -> OllamaEmbedder:
        return OllamaEmbedder(
            settings_override(embeddings={"provider": "ollama", **embeddings}).embeddings
        )

    return build


def _reply(request: httpx.Request) -> httpx.Response:
    inputs = json.loads(request.content)["input"]
    return httpx.Response(200, json={"embeddings": [[float(len(t)), 1.0] for t in inputs]})


@respx.mock
def test_documents_carry_the_prefix_and_the_model(make: Callable[..., OllamaEmbedder]) -> None:
    route = respx.post(URL).mock(side_effect=_reply)
    vectors = make().embed_documents(["abc", "de"])
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "model": "nomic-embed-text",
        "input": ["search_document: abc", "search_document: de"],
    }
    assert vectors == [
        [float(len("search_document: abc")), 1.0],
        [float(len("search_document: de")), 1.0],
    ]


@respx.mock
def test_query_uses_the_query_prefix(make: Callable[..., OllamaEmbedder]) -> None:
    route = respx.post(URL).mock(side_effect=_reply)
    vector = make().embed_query("what is mfa")
    assert json.loads(route.calls[0].request.content)["input"] == ["search_query: what is mfa"]
    assert vector == [float(len("search_query: what is mfa")), 1.0]


@respx.mock
def test_texts_are_sent_in_batches_and_order_is_kept(make: Callable[..., OllamaEmbedder]) -> None:
    route = respx.post(URL).mock(side_effect=_reply)
    texts = [f"t{n}" * (n + 1) for n in range(5)]
    vectors = make(batch_size=2).embed_documents(texts)
    sizes = [len(json.loads(c.request.content)["input"]) for c in route.calls]
    assert sizes == [2, 2, 1]
    assert [v[0] for v in vectors] == [float(len("search_document: ") + len(t)) for t in texts]


@respx.mock
def test_no_texts_means_no_request(make: Callable[..., OllamaEmbedder]) -> None:
    route = respx.post(URL).mock(side_effect=_reply)
    assert make().embed_documents([]) == []
    assert route.call_count == 0


@respx.mock
def test_trailing_slash_in_base_url_is_fine(make: Callable[..., OllamaEmbedder]) -> None:
    route = respx.post(URL).mock(side_effect=_reply)
    make(base_url="http://localhost:11434/").embed_query("x")
    assert route.called


@respx.mock
def test_http_error_becomes_embedding_error_with_the_server_message(
    make: Callable[..., OllamaEmbedder],
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(404, json={"error": "model 'x' not found"}))
    with pytest.raises(EmbeddingError, match=r"HTTP 404.*not found"):
        make().embed_query("x")


@respx.mock
def test_non_json_error_body_is_truncated(make: Callable[..., OllamaEmbedder]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, text="x" * 5000))
    with pytest.raises(EmbeddingError) as info:
        make().embed_query("x")
    assert len(str(info.value)) < 300


@respx.mock
@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_connection_problems_become_embedding_errors(
    make: Callable[..., OllamaEmbedder], exc: Exception
) -> None:
    respx.post(URL).mock(side_effect=exc)
    with pytest.raises(EmbeddingError, match=type(exc).__name__):
        make().embed_query("x")


@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": []},  # wrong count
        {"embeddings": [[1.0], [2.0]]},  # wrong count
        {"nope": 1},
        ["not", "a", "dict"],
        {"embeddings": [["a", "b"]]},
        {"embeddings": [[True, False]]},
        {"embeddings": [[]]},
        {"embeddings": [None]},
    ],
)
def test_malformed_responses_are_rejected(
    make: Callable[..., OllamaEmbedder], payload: object
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(EmbeddingError, match="unusable"):
        make().embed_query("x")


@respx.mock
def test_vectors_of_different_dimensions_are_rejected(make: Callable[..., OllamaEmbedder]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={"embeddings": [[1.0, 2.0], [1.0]]}))
    with pytest.raises(EmbeddingError, match="dimensions"):
        make().embed_documents(["a", "b"])


@respx.mock
def test_integers_in_vectors_become_floats(make: Callable[..., OllamaEmbedder]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={"embeddings": [[1, 2]]}))
    vector = make().embed_query("x")
    assert vector == [1.0, 2.0] and all(isinstance(x, float) for x in vector)


@respx.mock
def test_non_json_success_body_is_an_embedding_error(make: Callable[..., OllamaEmbedder]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(EmbeddingError, match="unusable"):
        make().embed_query("x")
