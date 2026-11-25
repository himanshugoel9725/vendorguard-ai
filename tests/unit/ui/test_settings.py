"""The ``ui`` settings: defaults, the secret, and the rule that the key only travels safely."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from vendorguard.config import Settings
from vendorguard.config_models.core import UiSettings

Make = Callable[..., Settings]


def test_defaults_point_at_the_local_api(settings_override: Make) -> None:
    ui = settings_override().ui
    assert ui.api_base_url == "http://127.0.0.1:8000" and ui.poll_interval_s >= 1
    assert ui.api_key.get_secret_value() == ""  # never in the YAML


def _ui(url: str, hosts: list[str] | None = None) -> UiSettings:
    return UiSettings(  # type: ignore[arg-type]
        api_base_url=url,
        api_key="k" * 20,
        request_timeout_s=5,
        poll_interval_s=3,
        poll_timeout_s=60,
        refresh_ttl_s=15,
        max_detail_chars=300,
        allowed_hosts=hosts or ["127.0.0.1"],
        page_title="t",
    )


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8000", "http://localhost:9", "http://[::1]:8000", "https://api.example.org"],
)
def test_safe_addresses_are_accepted(url: str) -> None:
    assert _ui(url).api_base_url == url


@pytest.mark.parametrize(
    "url", ["http://api.example.org", "ftp://127.0.0.1", "not a url", "http://"]
)
def test_the_key_is_never_sent_over_plain_http_to_another_machine(url: str) -> None:
    with pytest.raises(ValidationError):
        _ui(url)


def test_the_ui_key_is_redacted_like_every_secret(settings_override: Make) -> None:
    from vendorguard.logging_setup import collect_secrets

    s = settings_override(ui={"api_key": "ui-key-" + "x" * 20})
    assert "ui-key-" + "x" * 20 in collect_secrets(s)


def test_the_host_allowlist_cannot_be_empty() -> None:
    with pytest.raises(ValidationError, match="allowed_hosts"):
        UiSettings(
            api_base_url="http://127.0.0.1:8000",
            api_key="k" * 20,
            request_timeout_s=5,
            poll_interval_s=3,
            poll_timeout_s=60,
            refresh_ttl_s=15,
            max_detail_chars=300,
            allowed_hosts=[],
            page_title="t",
        )  # type: ignore[arg-type]


def test_defaults_allow_only_this_machine(settings_override: Make) -> None:
    ui = settings_override().ui
    assert set(ui.allowed_hosts) == {"127.0.0.1", "localhost", "[::1]"}
