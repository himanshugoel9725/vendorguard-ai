"""Load and validate a control set from YAML (``paths.controls_file``)."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from vendorguard.errors import ConfigError
from vendorguard.models.control import ControlSet


def _describe(path: Path, exc: ValidationError, raw: dict[str, Any]) -> str:
    """Summarise validation errors with the control ID where known (no input values echoed)."""
    found = raw.get("controls")
    controls: list[Any] = found if isinstance(found, list) else []
    lines = []
    for err in exc.errors():
        loc = list(err["loc"])
        where = ".".join(str(part) for part in loc) or "file"
        if loc[:1] == ["controls"] and len(loc) > 1 and isinstance(loc[1], int):
            entry = controls[loc[1]] if loc[1] < len(controls) else None
            label = entry.get("id") if isinstance(entry, dict) else None
            if label:
                where = f"controls[{loc[1]}] ({label})." + ".".join(str(p) for p in loc[2:])
        message = "missing" if err["type"] == "missing" else err["msg"]
        lines.append(f"{where.rstrip('.')}: {message}")
    return f"invalid control set {path}:\n  " + "\n  ".join(sorted(lines))


def load_controls(path: Path) -> ControlSet:
    """Load ``path`` into a ``ControlSet`` sorted by control ID.

    Raises ConfigError with the file name and the offending control for a missing file, bad YAML,
    a wrong shape, duplicate IDs, unknown domains or empty keyword lists.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read control set {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"control set {path} must contain a YAML mapping")
    try:
        controls = ControlSet.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_describe(path, exc, raw)) from exc
    return controls.model_copy(update={"controls": sorted(controls.controls, key=lambda c: c.id)})


__all__ = ["load_controls"]
