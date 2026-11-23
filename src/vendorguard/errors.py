"""Exception hierarchy: every error raised on purpose derives from VendorGuardError."""


class VendorGuardError(Exception):
    """Base class for every error raised on purpose by VendorGuard.

    ``paid_usage`` is ``(tokens_in, tokens_out)`` that an LLM call had already paid for when it
    failed (for example repair attempts), so the budget guard can still charge them.
    """

    paid_usage: tuple[int, int] | None = None


class ConfigError(VendorGuardError):
    """Configuration is missing, invalid or unsafe (for example a secret in YAML)."""


class IngestError(VendorGuardError):
    """A document cannot be loaded (wrong type, too large, encrypted, scanned, unreadable)."""


class ProviderError(VendorGuardError):
    """Base class for failures of a swappable provider."""


class LLMError(ProviderError):
    """The LLM provider failed (connection, timeout, HTTP error, unusable response)."""


class EmbeddingError(ProviderError):
    """The embedding provider failed."""


class DeciderError(ProviderError):
    """The decision provider (rule, LLM-judge or Jev) failed."""


class MemoryStoreError(ProviderError):
    """The memory store (SQLite or Letta) failed."""


class SchemaValidationError(VendorGuardError):
    """Model output did not validate against its Pydantic schema, even after repair attempts."""


class CacheMissError(VendorGuardError):
    """A read-only cache had no entry for a call (re-record with ``make record``)."""


class BudgetExceededError(VendorGuardError):
    """A configured cost or call budget was exceeded; the run was stopped."""


__all__ = [
    "BudgetExceededError",
    "CacheMissError",
    "ConfigError",
    "DeciderError",
    "EmbeddingError",
    "IngestError",
    "LLMError",
    "MemoryStoreError",
    "ProviderError",
    "SchemaValidationError",
    "VendorGuardError",
]
