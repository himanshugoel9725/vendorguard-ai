"""Inherent risk: the tier comes from the data categories and the settings rules."""

from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.scoring import InherentRiskSettings
from vendorguard.models.score import InherentTier
from vendorguard.models.vendor import DataCategory, VendorProfile
from vendorguard.scoring.inherent_risk import NO_REASON_TEXT, inherent_risk


def _profile(*categories: DataCategory) -> VendorProfile:
    return VendorProfile(
        vendor_name="V", services=[], data_categories=list(categories), hosting=[],
        certifications=[], subprocessors=[],
    )  # fmt: skip


@pytest.fixture
def rules(settings_override: Callable[..., Settings]) -> InherentRiskSettings:
    return settings_override().scoring.inherent_risk


@pytest.mark.parametrize(
    ("categories", "tier"),
    [
        ([DataCategory.FINANCIAL], InherentTier.HIGH),
        ([DataCategory.HEALTH], InherentTier.HIGH),
        ([DataCategory.CREDENTIALS], InherentTier.HIGH),
        ([DataCategory.PII], InherentTier.MEDIUM),
        ([DataCategory.CUSTOMER_CONTENT], InherentTier.MEDIUM),
        ([DataCategory.PII, DataCategory.CUSTOMER_CONTENT], InherentTier.MEDIUM),
        ([DataCategory.PII, DataCategory.FINANCIAL], InherentTier.HIGH),  # the highest tier wins
        ([DataCategory.NONE], InherentTier.LOW),
        ([], InherentTier.LOW),
    ],
)
def test_tier_from_categories(
    rules: InherentRiskSettings, categories: list[DataCategory], tier: InherentTier
) -> None:
    assert inherent_risk(_profile(*categories), rules).tier is tier


def test_reasons_name_the_deciding_categories_sorted(rules: InherentRiskSettings) -> None:
    risk = inherent_risk(
        _profile(DataCategory.PII, DataCategory.HEALTH, DataCategory.FINANCIAL), rules
    )
    assert risk.reasons == [
        "handles financial data, which puts the vendor in the high tier",
        "handles health data, which puts the vendor in the high tier",
    ]  # pii is medium and not mentioned: only the deciding tier's categories are listed


def test_medium_and_low_reasons(rules: InherentRiskSettings) -> None:
    assert inherent_risk(_profile(DataCategory.PII), rules).reasons == [
        "handles pii data, which puts the vendor in the medium tier"
    ]
    assert inherent_risk(_profile(DataCategory.NONE), rules).reasons == [NO_REASON_TEXT]
    assert inherent_risk(_profile(), rules).reasons == [NO_REASON_TEXT]


def test_the_result_does_not_depend_on_the_order_or_repeats_of_categories(
    rules: InherentRiskSettings,
) -> None:
    a = inherent_risk(_profile(DataCategory.HEALTH, DataCategory.FINANCIAL), rules)
    b = inherent_risk(
        _profile(DataCategory.FINANCIAL, DataCategory.HEALTH, DataCategory.FINANCIAL), rules
    )
    assert a == b


def test_the_rules_come_from_settings(settings_override: Callable[..., Settings]) -> None:
    custom = settings_override(
        scoring={"inherent_risk": {"high_if_any": ["pii"], "medium_if_any": ["financial"]}}
    ).scoring.inherent_risk
    assert inherent_risk(_profile(DataCategory.PII), custom).tier is InherentTier.HIGH
    assert inherent_risk(_profile(DataCategory.FINANCIAL), custom).tier is InherentTier.MEDIUM
    assert inherent_risk(_profile(DataCategory.HEALTH), custom).tier is InherentTier.LOW


def test_empty_rule_lists_give_low(settings_override: Callable[..., Settings]) -> None:
    rules = settings_override(
        scoring={"inherent_risk": {"high_if_any": [], "medium_if_any": []}}
    ).scoring.inherent_risk
    assert inherent_risk(_profile(DataCategory.HEALTH), rules).tier is InherentTier.LOW
