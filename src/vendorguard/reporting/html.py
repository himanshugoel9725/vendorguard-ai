"""Self-contained HTML report (inline CSS, no scripts, no network). Autoescaping is always on."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(view: dict[str, Any]) -> str:
    """The full report as one HTML document."""
    return _ENV.get_template("report.html.j2").render(v=view)


__all__ = ["render_html"]
