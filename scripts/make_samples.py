"""Generate the synthetic sample vendors into ``paths.samples_dir`` (used by ``make sample``)."""

from vendorguard.config import get_settings
from vendorguard.eval.sample_gen import generate_all


def main() -> None:
    """Write every sample and print the SHA-256 of each file."""
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


if __name__ == "__main__":
    main()
