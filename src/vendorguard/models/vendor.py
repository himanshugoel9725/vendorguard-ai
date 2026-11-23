"""Vendor profile extracted by the Intake Agent (an LLM output schema, so every list is bounded)."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from vendorguard.models._base import ContractModel

# Schema bounds: part of the data contract sent to the LLM. Changing them changes the JSON schema,
# so it needs a new prompt version and re-recorded cassettes (see ADR-010).
MAX_ITEMS = 20
MAX_TEXT_CHARS = 200

ShortText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]
ShortList = Annotated[list[ShortText], Field(max_length=MAX_ITEMS)]


class DataCategory(StrEnum):
    """Kinds of customer data a vendor handles (drives inherent risk)."""

    PII = "pii"
    FINANCIAL = "financial"
    HEALTH = "health"
    CREDENTIALS = "credentials"
    CUSTOMER_CONTENT = "customer_content"
    NONE = "none"


class VendorProfile(ContractModel):
    """Facts about the vendor, extracted from its documents."""

    vendor_name: ShortText
    services: ShortList
    data_categories: Annotated[list[DataCategory], Field(max_length=len(DataCategory))]
    hosting: ShortList
    certifications: ShortList
    subprocessors: ShortList
    report_period: ShortText | None = None


__all__ = ["DataCategory", "VendorProfile"]
