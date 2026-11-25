"""Small safety helpers for text that reaches Streamlit widgets or spreadsheets."""

import re
from collections.abc import Sequence

MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~$&:])")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def plain(text: str) -> str:
    """Escape Markdown (links, images, emphasis, emoji codes, math) for widgets such as
    ``st.error`` or an expander label, which render Markdown. Prefer ``st.text`` where possible."""
    return MARKDOWN_SPECIAL.sub(r"\\\1", text)


def spreadsheet_safe(text: str) -> str:
    """Neutralise a leading ``= + - @`` so a table exported to CSV cannot run as a formula."""
    return "'" + text if text.startswith(FORMULA_START) else text


def host_allowed(host_header: str | None, allowed: Sequence[str]) -> bool:
    """True if the request's ``Host`` header names one of the allowed hosts (any port). Attackers
    who rebind a DNS name to this machine still send their own name here. A request without the
    header (not a browser) is let through: it carries no attacker-chosen name."""
    if host_header is None:
        return True
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8501
        name = host[: host.find("]") + 1] if "]" in host else host
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in {h.lower() for h in allowed}


__all__ = ["host_allowed", "plain", "spreadsheet_safe"]
