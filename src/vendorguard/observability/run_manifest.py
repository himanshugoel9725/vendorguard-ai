"""Run manifest: what a run used and produced, enough to reproduce and audit it (no secrets)."""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from vendorguard import __version__
from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.models.run import AssessmentResult, ManifestInput, RunManifest, RunStatus
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.jsonio import read_json, write_json
from vendorguard.utils.timeutil import utcnow

# Fields that change from run to run without changing the assessment itself.
VOLATILE_RESULT_FIELDS = {"created_at", "cost", "manifest_path"}


def current_git_sha(cwd: Path, timeout_s: float) -> str | None:
    """The commit of the working tree, or None when git is missing or this is no checkout."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = done.stdout.strip()
    return sha if done.returncode == 0 and sha else None


def result_hash(result: AssessmentResult) -> str:
    """SHA-256 of the canonical result without its volatile fields (findings are sorted)."""
    return hash_obj(result.model_dump(mode="json", exclude=VOLATILE_RESULT_FIELDS))


def start_manifest(
    run_id: str,
    settings: Settings,
    *,
    controls_version: str,
    prompt_hashes: Mapping[str, str],
    providers: Mapping[str, str],
    inputs: Sequence[ManifestInput],
    git_sha: str | None = None,
) -> RunManifest:
    """The manifest of a run that has just started (status ``running``)."""
    return RunManifest(
        run_id=run_id,
        status=RunStatus.RUNNING,
        started_at=utcnow(),
        app_version=__version__,
        git_sha=git_sha,
        config_fingerprint=settings.fingerprint(),
        controls_version=controls_version,
        prompt_hashes=dict(sorted(prompt_hashes.items())),
        providers=dict(sorted(providers.items())),
        inputs=sorted(inputs, key=lambda i: (i.filename, i.sha256)),
    )


def finish_manifest(
    manifest: RunManifest, status: RunStatus, result_sha: str | None = None
) -> RunManifest:
    """A finished copy: ``done`` needs a result hash, ``failed`` has none."""
    if status is RunStatus.RUNNING:
        raise ConfigError("a finished manifest cannot have the status 'running'")
    if status is RunStatus.DONE and result_sha is None:
        raise ConfigError("a successful run needs a result hash")
    return manifest.model_copy(
        update={
            "status": status,
            "finished_at": utcnow(),
            "result_hash": result_sha if status is RunStatus.DONE else None,
        }
    )


def write_manifest(path: Path, manifest: RunManifest) -> None:
    """Write the manifest atomically (temp file, then rename)."""
    tmp = path.with_name(path.name + ".tmp")
    write_json(tmp, manifest.model_dump(mode="json"))
    tmp.replace(path)


def read_manifest(path: Path) -> RunManifest:
    """Read and validate a manifest file."""
    if not path.is_file():
        raise ConfigError(f"manifest {path.name} not found")
    try:
        return RunManifest.model_validate(read_json(path))
    except ValueError as exc:
        raise ConfigError(f"manifest {path.name} is damaged") from exc


__all__ = [
    "VOLATILE_RESULT_FIELDS",
    "current_git_sha",
    "finish_manifest",
    "read_manifest",
    "result_hash",
    "start_manifest",
    "write_manifest",
]
