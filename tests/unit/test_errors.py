"""Tests for the exception hierarchy."""

import inspect

import pytest

from vendorguard import errors
from vendorguard.errors import (
    BudgetExceededError,
    CacheMissError,
    ConfigError,
    DeciderError,
    EmbeddingError,
    IngestError,
    LLMError,
    MemoryStoreError,
    ProviderError,
    SchemaValidationError,
    VendorGuardError,
)

ALL = [
    BudgetExceededError,
    CacheMissError,
    ConfigError,
    DeciderError,
    EmbeddingError,
    IngestError,
    LLMError,
    MemoryStoreError,
    ProviderError,
    SchemaValidationError,
    VendorGuardError,
]
PROVIDER_CHILDREN = [LLMError, EmbeddingError, DeciderError, MemoryStoreError]
DIRECT_CHILDREN = [
    ConfigError,
    IngestError,
    ProviderError,
    SchemaValidationError,
    CacheMissError,
    BudgetExceededError,
]


@pytest.mark.parametrize("cls", ALL)
def test_derives_from_base(cls: type[Exception]) -> None:
    assert issubclass(cls, VendorGuardError)
    assert issubclass(cls, Exception)


@pytest.mark.parametrize("cls", PROVIDER_CHILDREN)
def test_provider_children(cls: type[Exception]) -> None:
    assert issubclass(cls, ProviderError)
    assert cls.__bases__ == (ProviderError,)


@pytest.mark.parametrize("cls", DIRECT_CHILDREN)
def test_direct_children(cls: type[Exception]) -> None:
    assert cls.__bases__ == (VendorGuardError,)


@pytest.mark.parametrize("cls", [ConfigError, IngestError, SchemaValidationError, CacheMissError])
def test_non_provider_errors_are_not_provider_errors(cls: type[Exception]) -> None:
    assert not issubclass(cls, ProviderError)


@pytest.mark.parametrize("cls", ALL)
def test_has_docstring(cls: type[Exception]) -> None:
    assert inspect.getdoc(cls)
    assert "__doc__" in vars(cls)


def test_all_lists_every_error() -> None:
    assert sorted(errors.__all__) == sorted(c.__name__ for c in ALL)
    assert len(set(errors.__all__)) == len(errors.__all__)


def test_catch_by_base_and_message_preserved() -> None:
    with pytest.raises(VendorGuardError, match="boom ünï"):
        raise LLMError("boom ünï")
    with pytest.raises(ProviderError):
        raise MemoryStoreError("x")
