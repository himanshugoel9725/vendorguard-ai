"""``vg doctor``: configuration summary, secrets set/unset, and reachability of local services."""

import httpx
from pydantic import BaseModel, SecretStr
from rich.table import Table

from vendorguard.cli.common import console, guarded, load
from vendorguard.config import Settings


def secret_status(value: object, prefix: str = "") -> dict[str, bool]:
    """Path of every SecretStr in the settings -> whether it is set. Values are never read out."""
    found: dict[str, bool] = {}
    if isinstance(value, SecretStr):
        found[prefix] = bool(value.get_secret_value())
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            path = f"{prefix}.{name}" if prefix else name
            found.update(secret_status(getattr(value, name), path))
    return found


def _reachable(url: str, timeout: float) -> str:
    try:
        httpx.get(url, timeout=timeout, follow_redirects=False).raise_for_status()
    except httpx.HTTPError as exc:
        return f"not reachable ({type(exc).__name__})"
    return "ok"


def _checks(s: Settings) -> list[tuple[str, str]]:
    t = s.app.doctor_timeout_s
    out: list[tuple[str, str]] = []
    if "ollama" in (s.llm.provider, s.embeddings.provider):
        out.append(("Ollama", _reachable(f"{s.llm.base_url.rstrip('/')}/api/tags", t)))
    if s.memory.provider == "letta":
        out.append(("Letta", _reachable(f"{s.memory.letta.base_url.rstrip('/')}/v1/health/", t)))
    return out


@guarded
def doctor() -> None:
    """Show the active configuration, which keys are set, and whether local services answer."""
    s = load()
    config = Table("setting", "value", title="Configuration")
    for k, v in (
        ("environment", s.app.environment),
        ("llm", f"{s.llm.provider} / {s.llm.model}"),
        ("embeddings", s.embeddings.provider),
        ("decider", s.decision.provider),
        ("memory", s.memory.provider),
        ("cache", f"{s.cache.backend} ({s.cache.mode})" if s.cache.enabled else "off"),
        ("controls", str(s.paths.controls_file)),
        ("runs folder", str(s.paths.runs_dir)),
    ):
        config.add_row(k, v)
    console.print(config)
    keys = Table("key", "state", title="Secrets (values are never shown)")
    for path, is_set in sorted(secret_status(s).items()):
        keys.add_row(path, "set" if is_set else "unset")
    console.print(keys)
    services = Table("service", "state", title="Services")
    for name, state in _checks(s):
        services.add_row(name, state)
    console.print(services)


__all__ = ["doctor", "secret_status"]
