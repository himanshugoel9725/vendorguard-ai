"""Mock Intake Agent: pulls vendor facts out of text with fixed patterns (no model)."""

import re
from typing import Any

from vendorguard.models.vendor import MAX_ITEMS, MAX_TEXT_CHARS, DataCategory

UNKNOWN_VENDOR = "Unknown vendor"
_NAME = re.compile(r"Security & Trust Overview\s+(.+?)\s+Reporting period", re.DOTALL)
_PERIOD = re.compile(r"Reporting period:\s*([^.]+)\.")
_LISTS = {
    "services": re.compile(r"Services:\s*(.+?)\.(?:\s|$)", re.DOTALL),
    "hosting": re.compile(r"Hosting:\s*(.+?)\.(?:\s|$)", re.DOTALL),
    "subprocessors": re.compile(r"Key suppliers:\s*(.+?)\.(?:\s|$)", re.DOTALL),
}
_CERTIFICATIONS = re.compile(
    r"SOC\s?2\s+Type\s+(?:II|I|2|1)\b|SOC\s?2\b|ISO(?:/IEC)?\s?27001(?::\d{4})?|PCI[ -]DSS|HIPAA"
)
# Cues for each data category, in the wording the sample documents use plus common variants.
_CATEGORY_CUES: dict[DataCategory, re.Pattern[str]] = {
    DataCategory.PII: re.compile(
        r"contact records|personal data|employee records|customer records|\bPII\b", re.IGNORECASE
    ),
    DataCategory.FINANCIAL: re.compile(
        r"bank account|bank details|payment details|payroll|credit card|salary", re.IGNORECASE
    ),
    DataCategory.HEALTH: re.compile(
        r"health and benefits|medical|patient|health records", re.IGNORECASE
    ),
    DataCategory.CREDENTIALS: re.compile(
        r"login details|customer credentials|user credentials|credential (?:vault|store)",
        re.IGNORECASE,
    ),
    DataCategory.CUSTOMER_CONTENT: re.compile(
        r"uploaded by customers|customer files|customer content|datasets uploaded", re.IGNORECASE
    ),
}
_NONE_CUE = re.compile(r"business contact details only", re.IGNORECASE)


def _items(pattern: re.Pattern[str], text: str) -> list[str]:
    match = pattern.search(text)
    if not match:
        return []
    parts = [" ".join(p.split()) for p in match.group(1).split(";")]
    return [p[:MAX_TEXT_CHARS] for p in parts if p][:MAX_ITEMS]


def extract_profile(text: str) -> dict[str, Any]:
    """A ``VendorProfile`` as a dict, built from the cover-page patterns in ``text``."""
    name = _NAME.search(text)
    period = _PERIOD.search(text)
    categories = [c.value for c, cue in _CATEGORY_CUES.items() if cue.search(text)]
    if not categories and _NONE_CUE.search(text):
        categories = [DataCategory.NONE.value]
    certifications = list(dict.fromkeys(" ".join(m.split()) for m in _CERTIFICATIONS.findall(text)))
    return {
        "vendor_name": " ".join(name.group(1).split())[:MAX_TEXT_CHARS] if name else UNKNOWN_VENDOR,
        "services": _items(_LISTS["services"], text),
        "data_categories": categories,
        "hosting": _items(_LISTS["hosting"], text),
        "certifications": certifications[:MAX_ITEMS],
        "subprocessors": _items(_LISTS["subprocessors"], text),
        "report_period": " ".join(period.group(1).split()) if period else None,
    }


__all__ = ["UNKNOWN_VENDOR", "extract_profile"]
