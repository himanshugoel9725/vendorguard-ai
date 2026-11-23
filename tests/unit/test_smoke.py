"""Smoke test: the package imports and exposes a version."""

import vendorguard


def test_package_exposes_version() -> None:
    """The package imports and has a non-empty version string."""
    assert vendorguard.__version__
