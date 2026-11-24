"""Canonical JSON report: the result plus the manifest and the audit summary."""

from typing import Any

from vendorguard.models.run import AssessmentResult
from vendorguard.utils.jsonio import canonical_json


def render_json(
    result: AssessmentResult, manifest: dict[str, Any] | None, audit: dict[str, Any] | None
) -> str:
    """Identical input gives identical text (sorted keys, no whitespace), plus a newline."""
    body = {"result": result.model_dump(mode="json"), "manifest": manifest, "audit_summary": audit}
    return canonical_json(body) + "\n"


__all__ = ["render_json"]
