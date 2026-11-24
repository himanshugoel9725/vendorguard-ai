"""``vg samples``: the synthetic sample vendors."""

from rich.markup import escape
from rich.table import Table

from vendorguard.cli.common import console, guarded, load
from vendorguard.eval.specs import load_spec


@guarded
def samples() -> None:
    """List the synthetic sample vendors and their documents (make sample creates them)."""
    settings = load()
    table = Table("sample", "vendor id", "name", "period", "inherent", "document")
    for spec_file in sorted((settings.paths.samples_dir / "specs").glob("*.yaml")):
        spec = load_spec(spec_file)
        doc = settings.paths.samples_dir / f"{spec_file.stem}.pdf"
        document = str(doc) if doc.is_file() else "missing: run make sample"
        tier = spec.expected_inherent_tier.value
        table.add_row(
            spec_file.stem,
            spec.vendor_id,
            escape(spec.vendor_name),
            spec.report_period,
            tier,
            document,
        )
    console.print(table)


__all__ = ["samples"]
