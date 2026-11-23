"""Logging setup: rich console or JSON lines, with secret redaction (docs/PLAN.md task 1.4)."""

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, SecretStr
from rich.console import Console
from rich.logging import RichHandler

from vendorguard.config_models.core import AppSettings

REDACTED = "***"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    (re.compile(r"\b(?:sk|gsk)[-_][A-Za-z0-9_-]{8,}"), REDACTED),
)
_HANDLER_TAG = "_vendorguard_handler"


class RedactingFilter(logging.Filter):
    """Masks known secret values and ``Bearer ...`` / ``sk-...`` / ``gsk_...`` tokens."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        """Return ``text`` with every secret replaced by ``***``."""
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the message, exception text and stack info in place; never drops a record."""
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg, record.args = self.redact(message), None
        if record.exc_info:
            if record.exc_text is None:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line with stable key order."""

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a JSON line."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_text:
            payload["exception"] = record.exc_text
        elif record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def collect_secrets(value: Any) -> list[str]:
    """Return every non-empty SecretStr value found inside a settings object."""
    if isinstance(value, SecretStr):
        secret = value.get_secret_value()
        return [secret] if secret else []
    if isinstance(value, BaseModel):
        return [s for name in type(value).model_fields for s in collect_secrets(getattr(value, name))]
    if isinstance(value, dict):
        return [s for item in value.values() for s in collect_secrets(item)]
    if isinstance(value, list | tuple):
        return [s for item in value for s in collect_secrets(item)]
    return []


def setup_logging(app: AppSettings, secrets: Iterable[str] = ()) -> None:
    """Install the root handler (rich console or JSON lines) with redaction; safe to call twice."""
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(old)
        old.close()
    handler: logging.Handler
    if app.log_json:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        handler = RichHandler(console=Console(stderr=True), show_path=False, markup=False)
    handler.addFilter(RedactingFilter(secrets))
    setattr(handler, _HANDLER_TAG, True)
    root.addHandler(handler)
    root.setLevel(app.log_level)


__all__ = ["REDACTED", "JsonFormatter", "RedactingFilter", "collect_secrets", "setup_logging"]
