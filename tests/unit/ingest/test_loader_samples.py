"""The loaders read every committed sample with the right page count (task 3.1 done-when)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.ingest.loader import load_document

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


@pytest.mark.parametrize("stem", STEMS)
@pytest.mark.parametrize("suffix", ["pdf", "txt"])
def test_sample_loads_with_the_page_count_in_its_evidence_map(
    stem: str, suffix: str, project_root: Path, settings_override: Callable[..., Settings]
) -> None:
    """PDF and text twin both load, with as many pages as the generator recorded."""
    evidence = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text("utf-8"))
    doc = load_document(project_root / f"data/samples/{stem}.{suffix}", settings_override().ingest)
    assert len(doc.pages) == evidence["page_count"] == 9
    assert doc.filename == f"{stem}.{suffix}"
    assert doc.media_type == ("application/pdf" if suffix == "pdf" else "text/plain")
    assert doc.doc_id == doc.sha256[:16]
    for entry in evidence["controls"].values():
        if entry["sentence"] and suffix == "txt":
            assert entry["sentence"] in doc.pages[entry["page"] - 1].text
