"""Tests for vendorguard.utils.timeutil."""

from datetime import UTC, datetime, timedelta

from vendorguard.utils import timeutil
from vendorguard.utils.timeutil import utcnow


def test_utcnow_is_aware_utc() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_utcnow_non_decreasing() -> None:
    first = utcnow()
    second = utcnow()
    assert second >= first


def test_utcnow_can_be_frozen(monkeypatch) -> None:
    frozen = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    monkeypatch.setattr("vendorguard.utils.timeutil.utcnow", lambda: frozen)
    assert timeutil.utcnow() == frozen
