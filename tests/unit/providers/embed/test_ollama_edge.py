"""Edge cases for OllamaEmbedder: batching, errors, transport failures, odd payloads."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from vendorguard.config import Settings
from vendorguard.errors import EmbeddingError
from vendorguard.providers.embed.ollama import MAX_ERROR_CHARS, OllamaEmbedder

SettingsFactory = Callable[..., Settings]


def _make(
    settings_override: SettingsFactory, batch_size: int = 3, **kw: Any
) -> tuple[OllamaEmbedder, str]:
    cfg = settings_override(embeddings={"provider": "ollama", "batch_size": batch_size}).embeddings
    return OllamaEmbedder(cfg, **kw), f"{cfg.base_url.rstrip('/')}/api/embed"


def _echo(request: httpx.Request) -> httpx.Response:
    inputs = json.loads(request.content)["input"]
    return httpx.Response(200, json={"embeddings": [[float(len(t)), 1.0] for t in inputs]})


@respx.mock
def test_url_keys_and_no_auth_header(settings_override: SettingsFactory) -> None:
    emb, url = _make(settings_override)
    route = respx.post(url).mock(side_effect=_echo)
    emb.embed_query("hi")
    req = route.calls[0].request
    assert str(req.url) == url and url.endswith("/api/embed")
    assert set(json.loads(req.content)) == {"model", "input"}
    assert "authorization" not in req.headers
    cfg = settings_override(embeddings={"provider": "ollama"}).embeddings
    assert emb.model == cfg.model


def test_injected_client_is_used_and_closed(settings_override: SettingsFactory) -> None:
    client = httpx.Client(transport=httpx.MockTransport(_echo))
    emb, _ = _make(settings_override, client=client)
    assert emb.embed_query("x")
    assert not client.is_closed
    emb.close()
    assert client.is_closed


@respx.mock
@pytest.mark.parametrize(
    ("size", "n", "sizes"), [(1, 3, [1, 1, 1]), (3, 6, [3, 3]), (16, 25, [16, 9])]
)
def test_batching_shapes(
    settings_override: SettingsFactory, size: int, n: int, sizes: list[int]
) -> None:
    emb, url = _make(settings_override, batch_size=size)
    route = respx.post(url).mock(side_effect=_echo)
    texts = [f"t{'x' * i}" for i in range(n)]
    out = emb.embed_documents(texts)
    assert [len(json.loads(c.request.content)["input"]) for c in route.calls] == sizes
    assert [v[0] for v in out] == [float(len(emb._settings.doc_prefix + t)) for t in texts]


@respx.mock
def test_unicode_long_and_empty_texts_sent_unchanged(settings_override: SettingsFactory) -> None:
    emb, url = _make(settings_override)
    route = respx.post(url).mock(side_effect=_echo)
    texts = ["", "héllo 世界 🚀", "a" * 200_000]
    emb.embed_documents(texts)
    sent = json.loads(route.calls[0].request.content)["input"]
    prefix = emb._settings.doc_prefix
    assert sent == [prefix + t for t in texts]


@respx.mock
def test_extra_keys_and_mixed_numbers_accepted(settings_override: SettingsFactory) -> None:
    emb, url = _make(settings_override)
    respx.post(url).mock(
        return_value=httpx.Response(
            200, json={"model": "m", "total_duration": 5, "embeddings": [[1, 2.5]]}
        )
    )
    vec = emb.embed_query("q")
    assert vec == [1.0, 2.5] and all(type(x) is float for x in vec)


@respx.mock
def test_200_with_error_key_is_embedding_error(settings_override: SettingsFactory) -> None:
    emb, url = _make(settings_override)
    respx.post(url).mock(return_value=httpx.Response(200, json={"error": "boom"}))
    with pytest.raises(EmbeddingError):
        emb.embed_query("q")


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_http_statuses_named_and_text_not_leaked(
    settings_override: SettingsFactory, status: int
) -> None:
    emb, url = _make(settings_override)
    respx.post(url).mock(return_value=httpx.Response(status, json={"error": "e" * 1000}))
    with pytest.raises(EmbeddingError, match=str(status)) as info:
        emb.embed_query("SECRET-TEXT")
    msg = str(info.value)
    assert "SECRET-TEXT" not in msg
    assert msg.count("e") <= MAX_ERROR_CHARS + 20


@respx.mock
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("t"),
        httpx.ReadError("r"),
        httpx.RemoteProtocolError("p"),
        httpx.TooManyRedirects("m"),
    ],
)
def test_transport_errors_chain_and_name(
    settings_override: SettingsFactory, exc: Exception
) -> None:
    emb, url = _make(settings_override)
    respx.post(url).mock(side_effect=exc)
    with pytest.raises(EmbeddingError, match=type(exc).__name__) as info:
        emb.embed_query("SECRET-TEXT")
    assert info.value.__cause__ is exc
    assert "SECRET-TEXT" not in str(info.value)


@respx.mock
def test_second_batch_failure_returns_nothing(settings_override: SettingsFactory) -> None:
    emb, url = _make(settings_override, batch_size=2)
    route = respx.post(url).mock(
        side_effect=[
            httpx.Response(200, json={"embeddings": [[1.0], [2.0]]}),
            httpx.Response(500, json={"error": "down"}),
        ]
    )
    with pytest.raises(EmbeddingError, match="500"):
        emb.embed_documents(["a", "b", "c"])
    assert route.call_count == 2


@respx.mock
def test_query_failure_is_embedding_error(settings_override: SettingsFactory) -> None:
    emb, url = _make(settings_override)
    respx.post(url).mock(return_value=httpx.Response(503, text="unavailable"))
    with pytest.raises(EmbeddingError, match="503"):
        emb.embed_query("q")


@respx.mock
@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected(settings_override: SettingsFactory, token: str) -> None:
    """Python's json accepts bare NaN/Infinity; they would poison cosine similarity."""
    emb, url = _make(settings_override)
    body = f'{{"embeddings": [[1.0, {token}]]}}'.encode()
    respx.post(url).mock(return_value=httpx.Response(200, content=body))
    with pytest.raises(EmbeddingError, match="unusable.*NaN or infinite"):
        emb.embed_query("q")
