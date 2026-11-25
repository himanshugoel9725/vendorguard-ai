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


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_default_permissions_are_read_only(path: Path) -> None:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicates)  # noqa: S506
    assert data["permissions"] == {"contents": "read"}, "elevate per job, not for the workflow"
    elevated = {
        name
        for name, job in data["jobs"].items()
        if job.get("permissions", {}) != {} and set(job["permissions"]) - {"contents"}
    }
    allowed = {"ci.yml": set(), "pages.yml": {"deploy"}, "release.yml": {"image", "release"}}
    assert elevated <= allowed[path.name], f"unexpected elevated jobs: {elevated}"


def test_release_pushes_only_from_a_tag_or_main() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'refs/tags/v*) echo "push=true"' in text
    assert "is not on main" in text  # a tag outside main is refused
    assert "docker push" in text and "build-push-action" in text  # the tested image is pushed
