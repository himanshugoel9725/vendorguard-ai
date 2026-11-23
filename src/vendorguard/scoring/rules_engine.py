"""The rules engine: residual-risk score, band and hard rules. Pure Python, no model.

Per control: ``risk = status_points[status] x criticality_weight``. Overall =
``100 x sum(risk) / sum(weight) x inherent multiplier`` capped at 100; a domain score is the same
without the multiplier. All sums use exact decimals and round half up to one decimal, so the
result never depends on float ordering. An analyst override replaces the status
(``effective_status``).
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from vendorguard.config_models.scoring import ScoringSettings
from vendorguard.errors import ConfigError
from vendorguard.models.control import ControlSet
from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.score import InherentTier, RiskBand, RiskScore
from vendorguard.scoring.bands import at_least, band_for

ONE_DECIMAL = Decimal("0.1")
HUNDRED = Decimal(100)
FLOOR_STATUSES = frozenset({ControlStatus.NOT_MET, ControlStatus.NO_EVIDENCE})


def _d(value: float) -> Decimal:
    return Decimal(str(value))


def _round(value: Decimal) -> float:
    return float(min(value, HUNDRED).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP))


def score_findings(
    findings: Sequence[ControlFinding],
    controls: ControlSet,
    inherent: InherentTier,
    settings: ScoringSettings,
) -> RiskScore:
    """Score the findings. Controls without a finding (a subset run) are not counted."""
    by_id = {c.id: c for c in controls.controls}
    weights = settings.criticality_weights
    points = settings.status_points
    risk_by_domain: dict[str, Decimal] = {}
    weight_by_domain: dict[str, Decimal] = {}
    triggered: list[str] = []
    floor = RiskBand(settings.critical_control_floor)
    for finding in sorted(findings, key=lambda f: f.control_id):
        control = by_id.get(finding.control_id)
        if control is None:
            raise ConfigError(f"finding for unknown control '{finding.control_id}'")
        status = finding.effective_status
        weight = _d(getattr(weights, control.criticality.value))
        risk = _d(getattr(points, status.value)) * weight
        risk_by_domain[control.domain] = risk_by_domain.get(control.domain, Decimal(0)) + risk
        weight_by_domain[control.domain] = weight_by_domain.get(control.domain, Decimal(0)) + weight
        if control.criticality.value == "critical" and status in FLOOR_STATUSES:
            triggered.append(
                f"critical_control_floor: {control.id} is {status.value}, "
                f"so the band is at least {floor.value}"
            )
    total_weight = sum(weight_by_domain.values(), Decimal(0))
    if total_weight == 0:
        raise ConfigError("there are no findings to score")
    ratio = sum(risk_by_domain.values(), Decimal(0)) / total_weight
    multiplier = _d(getattr(settings.inherent_risk.multiplier, inherent.value))
    overall = _round(HUNDRED * ratio * multiplier)
    band = band_for(overall, settings.bands)
    if triggered:
        band = at_least(band, floor)
    domain_scores = {
        d: _round(HUNDRED * risk_by_domain[d] / weight_by_domain[d]) for d in sorted(risk_by_domain)
    }
    return RiskScore(
        overall=overall, band=band, domain_scores=domain_scores, triggered_rules=triggered
    )


__all__ = ["score_findings"]
