"""Generate the synthetic sample vendors and their golden labels (used by ``make sample``)."""

from vendorguard.config import get_settings
from vendorguard.controls.loader import load_controls
from vendorguard.eval.golden import write_golden
from vendorguard.eval.sample_gen import generate_all


def main() -> None:
    """Write samples into ``paths.samples_dir`` and golden labels into ``paths.golden_dir``."""
    settings = get_settings()
    samples = generate_all(
        settings.samples,
        settings.decision.rule,
        settings.paths.controls_file,
        settings.paths.samples_dir,
    )
    for sample in samples:
        for name, digest in sorted(sample.sha256.items()):
            print(f"{digest}  {name}")
    control_ids = [c.id for c in load_controls(settings.paths.controls_file).controls]
    for path in write_golden(settings.samples.specs_dir, settings.paths.golden_dir, control_ids):
        print(f"golden labels written: {path}")


if __name__ == "__main__":
    main()
