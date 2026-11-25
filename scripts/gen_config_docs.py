"""Generate docs/CONFIG.md from the Settings models (types) and config/settings.yaml (defaults and
comments). ``python scripts/gen_config_docs.py`` writes the file, ``--check`` fails if it is stale.

The YAML is the single source of truth for defaults and descriptions: a comment on a key line (or
the comment block directly above it) becomes that key's description.
"""

import re
import sys
import types
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import yaml
from pydantic import BaseModel, SecretStr

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "config" / "settings.yaml"
OUT_PATH = ROOT / "docs" / "CONFIG.md"
SECRET_KEYS = frozenset({"api_key", "auth_key"})
MAX_DEFAULT_CHARS = 70  # longer defaults are cut in the table (the YAML has the full value)
KEY_LINE = re.compile(r"^(\s*)([A-Za-z0-9_]+):(?:\s+(.*))?$")
RULE_LINE = re.compile(r"^[#\s=\-]*$")

Path_ = tuple[str, ...]


def split_comment(value: str) -> tuple[str, str]:
    """``value`` split into (text, comment) at the first unquoted ``#`` after a space."""
    quote = ""
    for i, ch in enumerate(value):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1] in " \t"):
            return value[:i].rstrip(), value[i + 1 :].strip()
    return value.rstrip(), ""


def scan_yaml(text: str) -> tuple[dict[Path_, str], dict[str, str]]:
    """Descriptions by key path, and the introduction of each top-level section."""
    notes: dict[Path_, str] = {}
    intros: dict[str, str] = {}
    stack: list[tuple[int, str]] = []
    pending: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            pending = []
            continue
        if line.lstrip().startswith("#"):
            if not RULE_LINE.match(line):
                pending.append(line.lstrip("# ").strip())
            continue
        if line.lstrip().startswith("-"):
            pending = []
            continue
        match = KEY_LINE.match(line)
        if not match:
            pending = []
            continue
        indent, key, rest = len(match.group(1)), match.group(2), match.group(3) or ""
        while stack and indent <= stack[-1][0]:
            stack.pop()
        stack.append((indent, key))
        path = tuple(k for _, k in stack)
        _, trailing = split_comment(rest)
        if len(path) == 1:
            intros[key] = " ".join(pending + ([trailing] if trailing else []))
        else:
            notes[path] = " ".join(pending + ([trailing] if trailing else []))
        pending = []
    return notes, intros


def type_name(annotation: Any) -> str:
    """A short human type for a model field annotation."""
    origin = get_origin(annotation)
    if origin is Annotated:
        base, *meta = get_args(annotation)
        return _constrain(type_name(base), meta)
    if origin is Literal:
        return " \\| ".join(str(a) for a in get_args(annotation))
    if origin in (Union, types.UnionType):
        return " or ".join(type_name(a) for a in get_args(annotation) if a is not type(None))
    if origin is list:
        return f"list of {type_name(get_args(annotation)[0])}"
    if origin is dict:
        return "mapping"
    simple = {bool: "true/false", int: "integer", float: "number", str: "text", Path: "path"}
    if annotation in simple:
        return simple[annotation]
    if annotation is SecretStr:
        return "secret"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "section"
    return getattr(annotation, "__name__", str(annotation))


def _constrain(base: str, meta: list[Any]) -> str:
    bounds: dict[str, Any] = {}
    for item in meta:
        for sub in getattr(item, "metadata", [item]):
            for name in ("gt", "ge", "lt", "le"):
                if hasattr(sub, name):
                    bounds[name] = getattr(sub, name)
    if not bounds:
        return base
    low = f">= {bounds['ge']}" if "ge" in bounds else f"> {bounds['gt']}" if "gt" in bounds else ""
    high = f"<= {bounds['le']}" if "le" in bounds else f"< {bounds['lt']}" if "lt" in bounds else ""
    return f"{base} ({', '.join(x for x in (low, high) if x)})"


def field_types(model: type[BaseModel], prefix: Path_ = ()) -> dict[Path_, str]:
    """Type of every leaf field, by path (nested models are walked, not listed)."""
    out: dict[Path_, str] = {}
    for name, info in model.model_fields.items():
        annotation = info.annotation
        if _is_model(annotation):
            out.update(field_types(annotation, (*prefix, name)))
        else:
            out[(*prefix, name)] = _constrain(type_name(annotation), list(info.metadata))
    return out


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def leaves(data: dict[str, Any], model: type[BaseModel], prefix: Path_ = ()) -> dict[Path_, Any]:
    """Setting values by path: sections are walked through the model, so a mapping or a list
    field (prices, configs) is one setting."""
    out: dict[Path_, Any] = {}
    for key, value in data.items():
        annotation = model.model_fields[key].annotation
        if _is_model(annotation):
            out.update(leaves(value, annotation, (*prefix, key)))
        else:
            out[(*prefix, key)] = value
    return out


def show_default(path: Path_, value: Any) -> str:
    """The default as it appears in the table (secrets are never shown)."""
    if path[-1] in SECRET_KEYS:
        return "(secret: set in `.env`)"
    text = yaml.safe_dump(value, default_flow_style=True, width=10_000).strip()
    text = text.removesuffix("\n...").strip()
    if len(text) > MAX_DEFAULT_CHARS:
        text = text[: MAX_DEFAULT_CHARS - 1] + "…"
    return f"`{text}`".replace("|", "\\|")


def render(yaml_text: str, settings_model: type[BaseModel]) -> str:
    """The whole CONFIG.md text."""
    notes, intros = scan_yaml(yaml_text)
    values = leaves(yaml.safe_load(yaml_text), settings_model)
    types_ = field_types(settings_model)
    lines = [
        "# Configuration reference",
        "",
        "<!-- Generated by scripts/gen_config_docs.py from config/settings.yaml and the Settings "
        "models. Do not edit: run `make docs-config`. -->",
        "",
        "Every tunable lives in `config/settings.yaml`. Any value can be overridden with an "
        "environment variable named `VG_<SECTION>__<KEY>` (two underscores between levels), for "
        "example `VG_LLM__PROVIDER=mock`. Secrets are never stored in the YAML: put them in "
        "`.env` (see `.env.example`).",
        "",
    ]
    sections: dict[str, list[Path_]] = {}
    for path in values:
        sections.setdefault(path[0], []).append(path)
    for section, paths in sections.items():
        lines += [f"## `{section}`", ""]
        if intros.get(section):
            lines += [intros[section], ""]
        lines += ["| Key | Default | Type | Description |", "|---|---|---|---|"]
        for path in paths:
            key = ".".join(path)
            note = notes.get(path, "").replace("|", "\\|")
            kind = types_.get(path, "text")
            lines.append(f"| `{key}` | {show_default(path, values[path])} | {kind} | {note} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    """Write docs/CONFIG.md, or with ``--check`` verify that it is up to date."""
    sys.path.insert(0, str(ROOT / "src"))
    from vendorguard.config import Settings

    text = render(YAML_PATH.read_text(encoding="utf-8"), Settings)
    if "--check" in argv:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.is_file() else ""
        if current != text:
            print("docs/CONFIG.md is out of date: run `make docs-config`", file=sys.stderr)
            return 1
        return 0
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
