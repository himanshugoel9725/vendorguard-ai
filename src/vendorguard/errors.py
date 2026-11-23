"""Exception hierarchy (extended in task 1.4; ConfigError is needed by task 1.3)."""


class VendorGuardError(Exception):
    """Base class for every error raised on purpose by VendorGuard."""


class ConfigError(VendorGuardError):
    """Configuration is missing, invalid or unsafe (for example a secret in YAML)."""


__all__ = ["ConfigError", "VendorGuardError"]
