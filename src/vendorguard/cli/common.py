"""Shared CLI helpers: settings, friendly errors, exit codes, consoles."""

import functools
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console

from vendorguard.config import Settings, load_settings
from vendorguard.errors import ConfigError, IngestError, VendorGuardError
from vendorguard.logging_setup import collect_secrets, setup_logging

console = Console()
err_console = Console(stderr=True)

EXIT_FAILED = 1  # the run or a provider failed
EXIT_USAGE = 2  # bad input, bad configuration


def load(overrides: dict[str, Any] | None = None) -> Settings:
    """Load the settings (YAML + environment + ``.env``) and install redacting logging."""
    settings = load_settings(overrides=overrides)
    setup_logging(settings.app, collect_secrets(settings))
    return settings


def exit_code(exc: VendorGuardError) -> int:
    """Usage errors (configuration, unreadable input) are 2, everything else 1."""
    return EXIT_USAGE if isinstance(exc, ConfigError | IngestError) else EXIT_FAILED


def guarded[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Turn a VendorGuardError into one red line and an exit code (no traceback)."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except VendorGuardError as exc:
            err_console.print(f"[red]error:[/red] {exc}", markup=True, highlight=False)
            raise typer.Exit(exit_code(exc)) from exc

    return wrapper


__all__ = ["EXIT_FAILED", "EXIT_USAGE", "console", "err_console", "exit_code", "guarded", "load"]
