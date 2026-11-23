"""Risk bands: the band of a 0-100 score and the floor that hard rules can impose."""

from vendorguard.config_models.scoring import BandSettings
from vendorguard.models.score import RiskBand

ORDER = (RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL)


def band_for(score: float, bands: BandSettings) -> RiskBand:
    """The band whose inclusive upper bound is the first one at or above ``score``."""
    if score <= bands.low:
        return RiskBand.LOW
    if score <= bands.medium:
        return RiskBand.MEDIUM
    if score <= bands.high:
        return RiskBand.HIGH
    return RiskBand.CRITICAL


def at_least(band: RiskBand, floor: RiskBand) -> RiskBand:
    """The more severe of two bands."""
    return max(band, floor, key=ORDER.index)


__all__ = ["ORDER", "at_least", "band_for"]
