"""Canonical JSON: sorted keys, compact separators, ASCII, floats rounded to 6 decimal places."""

import json
import math
from datetime import date, datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel

FLOAT_DECIMALS = 6  # fixed by the determinism contract in docs/PLAN.md, not a tunable


def normalize(value: Any) -> Any:
    """Convert ``value`` into plain JSON types in a stable form (sets sorted, floats rounded)."""
    if isinstance(value, BaseModel):
        return normalize(value.model_dump())  # python mode keeps sets so they get sorted
    if isinstance(value, Enum):
        return normalize(value.value)
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN and infinity cannot be serialised canonically")
        return round(value, FLOAT_DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, dict):
        out = {str(key): normalize(item) for key, item in value.items()}
        if len(out) != len(value):
            raise ValueError("dict keys collide after str() conversion (for example 1 and '1')")
        return out
    if isinstance(value, list | tuple):
        return [normalize(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((normalize(item) for item in value), key=canonical_json)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, PurePath):
        return value.as_posix()
    raise TypeError(f"cannot serialise {type(value).__name__} canonically")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text of ``value`` (identical across runs and processes)."""
    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def write_json(path: Path, value: Any) -> None:
    """Write ``value`` as canonical JSON plus a newline, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    """Read a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["canonical_json", "normalize", "read_json", "write_json"]
