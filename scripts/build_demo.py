"""Assemble the demo part of the Pages site: copy each replayed report and write an index page.

Usage: ``python scripts/build_demo.py SITE_DIR STEM=RUNS_DIR [STEM=RUNS_DIR ...]``. Every RUNS_DIR
holds exactly one run folder (``result.json`` + ``report.html``). Output:
``SITE_DIR/demo/<stem>.html`` and ``SITE_DIR/demo/index.html``. Only synthetic, recorded data is
published.
"""

import html
import json
import re
import shutil
import sys
from pathlib import Path

STEM_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
INTRO = (
    "These are reports of four SYNTHETIC vendors, produced by VendorGuard AI replaying a recorded "
    "run of a small local model (qwen2.5:3b). No real vendor data is involved and no model is "
    "called when the site is built. The small model misses much of the evidence, so findings and "
    "scores here are NOT facts about the vendors: see the evaluation page for the measured "
    "accuracy."
)
STYLE = (
    "body{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem}"
    "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:.4rem .6rem;"
    "text-align:left}"
)


def find_run(runs_dir: Path) -> Path:
    """The only run folder inside ``runs_dir``."""
    found = sorted(p.parent for p in runs_dir.glob("*/result.json"))
    if len(found) != 1:
        raise SystemExit(f"{runs_dir}: expected exactly one run folder, found {len(found)}")
    return found[0]


def build(site: Path, runs: dict[str, Path]) -> Path:
    """Copy the reports into ``site/demo`` and write the index; returns the index path."""
    bad = [stem for stem in runs if not STEM_PATTERN.match(stem)]
    if bad:
        raise SystemExit(f"invalid demo name(s) {bad}: use letters, digits, - and _ only")
    demo = site / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    rows = []
    for stem in sorted(runs):
        run = find_run(runs[stem])
        result = json.loads((run / "result.json").read_text(encoding="utf-8"))
        shutil.copyfile(run / "report.html", demo / f"{stem}.html")
        score = result["score"]
        rows.append(
            '<tr><td><a href="{href}">{name}</a></td><td>{score:g}</td><td>{band}</td></tr>'.format(
                href=html.escape(f"{stem}.html", quote=True),
                name=html.escape(str(result["profile"]["vendor_name"])),
                score=score["overall"],
                band=html.escape(str(score["band"])),
            )
        )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>VendorGuard AI demo reports</title>"
        f"<style>{STYLE}</style></head><body><h1>VendorGuard AI demo reports</h1>"
        f"<p>{html.escape(INTRO)}</p>"
        "<table><tr><th>Vendor</th><th>Risk score</th><th>Band</th></tr>"
        + "".join(rows)
        + '</table><p><a href="../">Documentation</a></p></body></html>\n'
    )
    index = demo / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


def main(argv: list[str]) -> int:
    """Command line entry."""
    if len(argv) < 2 or any("=" not in a for a in argv[1:]):
        print(__doc__, file=sys.stderr)
        return 2
    runs = {a.split("=", 1)[0]: Path(a.split("=", 1)[1]) for a in argv[1:]}
    print(f"written: {build(Path(argv[0]), runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
