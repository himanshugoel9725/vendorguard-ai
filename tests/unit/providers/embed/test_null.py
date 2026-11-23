"""The ``none`` embedder."""

from vendorguard.providers.embed.null import NULL_MODEL, NullEmbedder


def test_returns_one_empty_vector_per_text() -> None:
    embedder = NullEmbedder()
    assert embedder.model == NULL_MODEL == "none"
    assert embedder.embed_documents(["a", "b", "c"]) == [[], [], []]
    assert embedder.embed_documents([]) == []
    assert embedder.embed_query("q") == []
