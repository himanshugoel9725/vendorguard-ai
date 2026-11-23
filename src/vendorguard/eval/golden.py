"""Golden labels: the true status of every control for each sample vendor, derived from its spec."""

import json
from pathlib import Path

from pydantic import ValidationError

from vendorguard.errors import ConfigError
from vendorguard.eval.specs import VendorSpec, check_covers, load_spec
from vendorguard.models._base import ContractModel, NonEmptyStr
from vendorguard.models.finding import DraftStatus
from vendorguard.models.score import InherentTier


class GoldenFile(ContractModel):
    """Contents of ``data/golden/<stem>.json``."""

    vendor_id: NonEmptyStr
    stem: NonEmptyStr
    report_period: NonEmptyStr
    expected_inherent_tier: InherentTier
    controls: dict[str, DraftStatus]


def build_golden(stem: str, spec: VendorSpec) -> GoldenFile:
    """Derive the golden labels from a spec: ``missing`` becomes ``no_evidence``."""
    return GoldenFile(
        vendor_id=spec.vendor_id,
        stem=stem,
        report_period=spec.report_period,
        expected_inherent_tier=spec.expected_inherent_tier,
        controls={cid: state.to_status() for cid, state in sorted(spec.controls.items())},
    )


def load_golden(path: Path) -> GoldenFile:
    """Read one golden file; raises ConfigError with the file name on any problem."""
    try:
        return GoldenFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise ConfigError(f"cannot read golden file {path}: {exc}") from exc


def write_golden(specs_dir: Path, golden_dir: Path, control_ids: list[str]) -> list[Path]:
    """Write ``<stem>.json`` for every spec (sorted keys, 2-space indent, trailing newline)."""
    golden_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in sorted(specs_dir.glob("*.yaml"), key=lambda p: p.stem):
        spec = load_spec(path)
        check_covers(spec, control_ids)
        text = json.dumps(
            build_golden(path.stem, spec).model_dump(mode="json"), sort_keys=True, indent=2
        )
        target = golden_dir / f"{path.stem}.json"
        target.write_text(text + "\n", encoding="ascii")
        written.append(target)
    return written


__all__ = ["GoldenFile", "build_golden", "load_golden", "write_golden"]
