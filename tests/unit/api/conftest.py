"""API tests: every ``settings_override`` carries a FAKE API key (the API refuses to start without
one). It lives here, not in the root conftest, because a key set through ``settings_override``
beats an environment variable and would hide the keys other tests set on purpose."""

from collections.abc import Callable
from typing import Any

import pytest

from vendorguard.config import Settings

TEST_API_KEY = "test-api-key-0123456789abcdef"  # gitleaks:allow (a fake, never a real secret)


@pytest.fixture
def settings_override(settings_override: Callable[..., Settings]) -> Callable[..., Settings]:
    """The root fixture with ``api.auth_key`` preset (an explicit ``api={...}`` still wins)."""

    def build(**overrides: Any) -> Settings:
        api = {"auth_key": TEST_API_KEY, **overrides.pop("api", {})}
        return settings_override(api=api, **overrides)

    return build
