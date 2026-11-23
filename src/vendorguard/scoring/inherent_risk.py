"""Inherent risk: how risky a vendor is from the data it handles, before looking at its controls."""

from vendorguard.config_models.scoring import InherentRiskSettings
from vendorguard.models.score import InherentRisk, InherentTier
from vendorguard.models.vendor import VendorProfile

NO_REASON_TEXT = "no data category that raises the tier was reported"


def inherent_risk(profile: VendorProfile, rules: InherentRiskSettings) -> InherentRisk:
    """The tier (high, medium or low) and the reasons for it.

    High if any reported data category is in ``scoring.inherent_risk.high_if_any``, otherwise
    medium if any is in ``medium_if_any``, otherwise low. The reasons name the categories that
    decided the tier, sorted, so the same profile always gives the same text.
    """
    reported = sorted({category.value for category in profile.data_categories})
    for tier, trigger in (
        (InherentTier.HIGH, rules.high_if_any),
        (InherentTier.MEDIUM, rules.medium_if_any),
    ):
        hits = [category for category in reported if category in trigger]
        if hits:
            reasons = [
                f"handles {category} data, which puts the vendor in the {tier.value} tier"
                for category in hits
            ]
            return InherentRisk(tier=tier, reasons=reasons)
    return InherentRisk(tier=InherentTier.LOW, reasons=[NO_REASON_TEXT])


__all__ = ["inherent_risk"]
