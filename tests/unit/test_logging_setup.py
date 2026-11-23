"""Tests for logging setup, redaction and the JSON formatter."""

import json
import logging
import re
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest

from vendorguard.config import Settings
from vendorguard.logging_setup import (
    REDACTED,
    JsonFormatter,
    RedactingFilter,
    collect_secrets,
    setup_logging,
)

AUTH = "fake-auth-key-123456"
API = "fake-api-key-abcdef"


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for h in list(root.handlers):
        if h not in handlers:
            root.removeHandler(h)
            h.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def _record(msg: str, args: object = None, **kw: object) -> logging.LogRecord:
    kw.setdefault("exc_info", None)
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, **kw)  # type: ignore[arg-type]


def _tagged() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, "_vendorguard_handler", False)]


# ---------- RedactingFilter ----------


def test_masks_configured_secret() -> None:
    f = RedactingFilter([AUTH])
    rec = _record(f"key={AUTH} end")
    assert f.filter(rec) is True
    assert rec.getMessage() == f"key={REDACTED} end"


def test_longest_secret_first() -> None:
    f = RedactingFilter(["abcdefgh", "abcdefghXYZ123"])
    assert f.redact("v=abcdefghXYZ123") == f"v={REDACTED}"
    assert "XYZ" not in f.redact("v=abcdefghXYZ123")


def test_empty_secrets_ignored() -> None:
    f = RedactingFilter(["", ""])
    assert f.redact("hello world") == "hello world"


@pytest.mark.parametrize("word", ["Bearer", "bearer", "BEARER"])
def test_masks_bearer(word: str) -> None:
    out = RedactingFilter().redact(f"Authorization: {word} abc.DEF-123_x=")
    assert "abc.DEF" not in out
    assert out.endswith("Bearer ***")


@pytest.mark.parametrize("token", ["sk-abcdefgh12", "gsk_abcdefgh12", "sk-proj_ABCD1234efgh"])
def test_masks_provider_tokens(token: str) -> None:
    out = RedactingFilter().redact(f"token {token} done")
    assert out == f"token {REDACTED} done"


@pytest.mark.parametrize("text", ["task-force-leader", "sk-short", "risk-assessment-team"])
def test_leaves_ordinary_words(text: str) -> None:
    assert RedactingFilter().redact(text) == text


def test_masks_percent_args() -> None:
    f = RedactingFilter([AUTH])
    rec = _record("value %s and %d", (AUTH, 3))
    assert f.filter(rec) is True
    assert rec.getMessage() == f"value {REDACTED} and 3"
    assert rec.args is None


def test_masks_exception_text() -> None:
    f = RedactingFilter([AUTH])
    try:
        raise ValueError(f"bad {AUTH}")
    except ValueError:
        import sys

        rec = _record("failed", exc_info=sys.exc_info())
    assert f.filter(rec) is True
    assert rec.exc_info is None
    assert rec.exc_text is not None
    assert AUTH not in rec.exc_text
    assert "ValueError" in rec.exc_text


def test_masks_existing_exc_text_and_stack_info() -> None:
    f = RedactingFilter([AUTH])
    rec = _record("m", sinfo=f"stack {AUTH}")
    rec.exc_text = f"trace {AUTH}"
    assert f.filter(rec) is True
    assert AUTH not in (rec.exc_text or "")
    assert AUTH not in (rec.stack_info or "")


def test_log_exception_through_logger() -> None:
    logger = logging.getLogger("vg.test.exc")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    h = Capture()
    h.addFilter(RedactingFilter([AUTH]))
    logger.addHandler(h)
    try:
        try:
            raise RuntimeError(AUTH)
        except RuntimeError:
            logger.exception("oops %s", AUTH)
    finally:
        logger.removeHandler(h)
    assert lines
    assert AUTH not in lines[0]


@pytest.mark.parametrize(
    ("msg", "args"), [("100%% bad args: %s", None), ("%s and %s", ("one",)), ("%d", ("x",))]
)
def test_malformed_calls_do_not_raise(msg: str, args: object) -> None:
    rec = _record(msg, args)
    assert RedactingFilter([AUTH]).filter(rec) is True


def test_redact_deterministic_and_unicode() -> None:
    f = RedactingFilter([AUTH])
    text = f"héllo ☃ {AUTH} " * 1000
    assert f.redact(text) == f.redact(text)
    assert AUTH not in f.redact(text)
    assert "☃" in f.redact(text)


# ---------- collect_secrets ----------


def test_collect_secrets_from_settings(
    monkeypatch: pytest.MonkeyPatch, settings_override: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("VG_API__AUTH_KEY", AUTH)
    monkeypatch.setenv("VG_LLM__OPENAI_COMPAT__API_KEY", API)
    found = collect_secrets(settings_override())
    assert sorted(found) == sorted([AUTH, API])


def test_collect_secrets_none_set(settings_override: Callable[..., Settings]) -> None:
    assert collect_secrets(settings_override()) == []


def test_collect_secrets_containers() -> None:
    from pydantic import SecretStr

    value = {"a": [SecretStr("one"), SecretStr("")], "b": (SecretStr("two"),), "c": "plain", "d": 3}
    assert sorted(collect_secrets(value)) == ["one", "two"]
    assert collect_secrets(None) == []


# ---------- JsonFormatter ----------


def test_json_formatter_basic() -> None:
    rec = _record("héllo ☃")
    line = JsonFormatter().format(rec)
    assert "\n" not in line
    assert line.isascii()
    data = json.loads(line)
    assert set(data) == {"ts", "level", "logger", "message"}
    assert data["message"] == "héllo ☃"
    assert data["level"] == "INFO"
    assert data["logger"] == "t"
    assert list(data) == sorted(data)
    ts = datetime.fromisoformat(data["ts"])
    assert ts.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_json_formatter_exception_and_multiline() -> None:
    import sys

    try:
        raise ValueError("bad")
    except ValueError:
        rec = _record("line1\nline2", exc_info=sys.exc_info())
    line = JsonFormatter().format(rec)
    assert "\n" not in line
    data = json.loads(line)
    assert "ValueError: bad" in data["exception"]
    assert data["message"] == "line1\nline2"


def test_json_formatter_deterministic() -> None:
    rec = _record("same")
    assert JsonFormatter().format(rec) == JsonFormatter().format(rec)


# ---------- setup_logging ----------


def test_single_handler_after_two_calls(settings_override: Callable[..., Settings]) -> None:
    app = settings_override(app={"log_json": True}).app
    setup_logging(app)
    setup_logging(app)
    assert len(_tagged()) == 1


def test_json_mode_output(
    capsys: pytest.CaptureFixture[str], settings_override: Callable[..., Settings]
) -> None:
    app = settings_override(app={"log_json": True}).app
    setup_logging(app, [AUTH])
    logging.getLogger("vg.json").warning("hello %s Bearer tok123456", AUTH)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["message"] == f"hello {REDACTED} Bearer {REDACTED}"
    assert data["logger"] == "vg.json"
    assert AUTH not in err


def test_console_mode_output(
    capsys: pytest.CaptureFixture[str], settings_override: Callable[..., Settings]
) -> None:
    app = settings_override(app={"log_json": False}).app
    setup_logging(app, [AUTH])
    logging.getLogger("vg.console").warning("hi %s", AUTH)
    captured = capsys.readouterr()
    assert AUTH not in captured.err + captured.out
    assert re.search(r"hi\s+\*\*\*", captured.err)


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_root_level_follows_setting(level: str, settings_override: Callable[..., Settings]) -> None:
    app = settings_override(app={"log_level": level}).app
    setup_logging(app)
    assert logging.getLogger().level == getattr(logging, level)


def test_level_filters_output(
    capsys: pytest.CaptureFixture[str], settings_override: Callable[..., Settings]
) -> None:
    app = settings_override(app={"log_json": True, "log_level": "ERROR"}).app
    setup_logging(app)
    logging.getLogger("vg.lvl").info("quiet")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("log_json", [True, False])
def test_secrets_from_settings_never_leak(
    log_json: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_override: Callable[..., Settings],
) -> None:
    monkeypatch.setenv("VG_API__AUTH_KEY", AUTH)
    monkeypatch.setenv("VG_LLM__OPENAI_COMPAT__API_KEY", API)
    settings = settings_override(app={"log_json": log_json})
    setup_logging(settings.app, collect_secrets(settings))
    log = logging.getLogger("vg.leak")
    log.error("a %s b %s", AUTH, API)
    try:
        raise RuntimeError(f"{AUTH}{API}")
    except RuntimeError:
        log.exception("failed")
    captured = capsys.readouterr()
    out = captured.err + captured.out
    assert AUTH not in out
    assert API not in out
    assert "RuntimeError" in out
