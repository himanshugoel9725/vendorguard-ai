"""Tests for vendorguard.utils.hashing."""

from vendorguard.utils.hashing import hash_obj, sha256_bytes, sha256_text

ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_text_known_vector() -> None:
    assert sha256_text("abc") == ABC


def test_sha256_bytes_matches_text() -> None:
    for text in ["abc", "", "héllo wörld ✓ 日本語"]:
        assert sha256_bytes(text.encode("utf-8")) == sha256_text(text)


def test_empty_input() -> None:
    assert sha256_text("") == EMPTY
    assert sha256_bytes(b"") == EMPTY


def test_unicode_is_utf8_and_deterministic() -> None:
    assert sha256_text("日本") == sha256_text("日本")
    assert sha256_text("é") != sha256_text("e")


def test_hash_obj_ignores_key_order() -> None:
    assert hash_obj({"a": 1, "b": [1, 2], "c": {"x": 1, "y": 2}}) == hash_obj(
        {"c": {"y": 2, "x": 1}, "b": [1, 2], "a": 1}
    )


def test_hash_obj_changes_with_value() -> None:
    assert hash_obj({"a": 1}) != hash_obj({"a": 2})
    assert hash_obj([1, 2]) != hash_obj([2, 1])


def test_hash_obj_is_hex_sha256() -> None:
    digest = hash_obj({"a": 1})
    assert len(digest) == 64
    assert digest == sha256_text('{"a":1}')
