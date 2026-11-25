"""GitHub workflow files: valid YAML without duplicate keys, actions pinned to commit SHAs."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


class _NoDuplicates(yaml.SafeLoader):
    pass


def _construct(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    keys = [loader.construct_object(key, deep=deep) for key, _ in node.value]
    duplicates = sorted({str(k) for k in keys if keys.count(k) > 1})
    if duplicates:
        raise ValueError(f"duplicate keys: {duplicates}")
    return loader.construct_mapping(node, deep)


_NoDuplicates.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct)


def test_there_are_workflows() -> None:
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "pages.yml", "release.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_and_pins_every_action(path: Path) -> None:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicates)  # noqa: S506
    uses = [
        step["uses"]
        for job in data["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    ]
    assert uses, f"{path.name} uses no action?"
    for ref in uses:
        assert PINNED.match(ref), f"{path.name}: '{ref}' is not pinned to a full commit SHA"
