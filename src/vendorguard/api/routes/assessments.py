"""Assessment routes: upload and start, poll, read the report, override a finding."""

import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUpload

from vendorguard.api.deps import get_controls, get_jobs, get_memory, get_settings
from vendorguard.api.jobs import Job, JobRegistry, JobState, QueueFull
from vendorguard.api.uploads import private_upload_dir, read_form, read_upload, save_upload
from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.control import ControlSet
from vendorguard.models.finding import ControlFinding, DraftStatus
from vendorguard.models.run import AssessmentResult, RunStatus
from vendorguard.models.score import RiskScore
from vendorguard.observability.run_manifest import read_manifest
from vendorguard.pipeline.override import apply_override
from vendorguard.pipeline.run_folder import MANIFEST_FILE
from vendorguard.pipeline.run_index import (
    RUN_ID_PATTERN,
    VENDOR_ID_PATTERN,
    read_result,
    run_path,
)
from vendorguard.reporting.render import FILES, render_reports
from vendorguard.utils.hashing import sha256_bytes
from vendorguard.utils.ids import make_run_id

router = APIRouter(prefix="/v1/assessments", tags=["assessments"])

RunId = Annotated[str, PathParam(pattern=RUN_ID_PATTERN.pattern, description="Run ID.")]
ControlId = Annotated[
    str, PathParam(pattern=r"^[A-Za-z]{2,5}-\d{2,3}$", description="Control ID, e.g. IAM-02.")
]
REPORT_TYPES = {"html": "text/html", "md": "text/markdown", "json": "application/json"}
REPORT_FILES = {"html": FILES["html"], "md": FILES["md"], "json": FILES["json"]}
HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
INTERRUPTED = "interrupted"


class Accepted(BaseModel):
    """The answer to a started assessment."""

    run_id: str
    status: JobState
    status_url: str


class AssessmentStatus(BaseModel):
    """Where a run is; ``result`` is present once it is done."""

    run_id: str
    status: JobState
    error: str | None = None
    result: AssessmentResult | None = None


class OverrideRequest(BaseModel):
    """An analyst's decision for one control."""

    status: DraftStatus
    reason: str = Field(min_length=1)  # upper bounds come from settings.api (checked in the route)
    analyst: str = Field(min_length=1)


class OverrideResponse(BaseModel):
    """The control after the override and the recomputed score."""

    finding: ControlFinding
    score: RiskScore


UPLOAD_SCHEMA: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["vendor_id", "files"],
                    "properties": {
                        "vendor_id": {"type": "string", "example": "nimbara-hr"},
                        "files": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "description": "PDF, TXT or MD vendor documents.",
                        },
                    },
                }
            }
        },
    }
}


@router.post(
    "",
    status_code=202,
    response_model=Accepted,
    summary="Upload vendor documents and start an assessment",
    openapi_extra=UPLOAD_SCHEMA,
)
async def start_assessment(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> Accepted:
    """Multipart form: ``vendor_id`` and one or more ``files``. Answers 202 with the run ID;
    poll ``GET /v1/assessments/{run_id}``. The same documents give the same run ID."""
    form = await read_form(request, settings)
    vendor_id = form.get("vendor_id")
    if not isinstance(vendor_id, str) or not VENDOR_ID_PATTERN.match(vendor_id):
        raise HTTPException(status_code=422, detail="vendor_id is missing or not valid")
    uploads = [f for f in form.getlist("files") if isinstance(f, StarletteUpload)]
    if not uploads:
        raise HTTPException(status_code=422, detail="at least one file is required")
    checked = [await read_upload(u, settings) for u in uploads]  # type: ignore[arg-type]
    hashes = sorted({sha256_bytes(data) for _, _, data in checked})
    run_id = make_run_id(
        vendor_id,
        hashes,
        settings.fingerprint(),
        deterministic=settings.pipeline.deterministic_run_ids,
    )
    folder = private_upload_dir(settings.paths.state_dir / "uploads")
    try:
        files = [save_upload(folder, i, ext, data) for i, (_, ext, data) in enumerate(checked)]
        job, created = jobs.submit(
            Job(run_id=run_id, vendor_id=vendor_id, folder=folder, files=files)
        )
    except QueueFull as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=503,
            detail="too many assessments are waiting",
            headers={"Retry-After": str(settings.api.retry_after_s)},
        ) from exc
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if not created:
        shutil.rmtree(folder, ignore_errors=True)  # the same run is already waiting or running
    return Accepted(run_id=job.run_id, status=job.state, status_url=f"/v1/assessments/{run_id}")


def _status_from_disk(runs_dir: Path, run_id: str) -> tuple[JobState, str | None, Path]:
    run_dir = run_path(runs_dir, run_id)  # 400-class ConfigError if unknown
    manifest = read_manifest(run_dir / MANIFEST_FILE)
    if manifest.status is RunStatus.DONE:
        return JobState.DONE, None, run_dir
    # 'failed', or 'running' with no job in this process: the server stopped mid-run.
    return JobState.FAILED, INTERRUPTED if manifest.status is RunStatus.RUNNING else None, run_dir


@router.get("/{run_id}", summary="Status of an assessment (with the result once done)")
def get_assessment(
    run_id: RunId,
    settings: Annotated[Settings, Depends(get_settings)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> AssessmentStatus:
    """``queued``, ``running``, ``failed`` (with the error class) or ``done`` with the result."""
    job = jobs.get(run_id)
    if job is not None and job.state in (JobState.QUEUED, JobState.RUNNING):
        return AssessmentStatus(run_id=run_id, status=job.state)
    try:
        state, error, run_dir = _status_from_disk(settings.paths.runs_dir, run_id)
    except ConfigError as exc:
        if job is not None:  # failed before the run folder existed
            return AssessmentStatus(run_id=run_id, status=job.state, error=job.error)
        raise HTTPException(status_code=404, detail="no such assessment") from exc
    if job is not None and job.state is JobState.FAILED and state is not JobState.DONE:
        state, error = JobState.FAILED, job.error  # a done run on disk wins over a failed re-run
    result = read_result(run_dir) if state is JobState.DONE else None
    return AssessmentStatus(run_id=run_id, status=state, error=error, result=result)


@router.get("/{run_id}/report", summary="The report of a finished assessment")
def get_report(
    run_id: RunId,
    settings: Annotated[Settings, Depends(get_settings)],
    controls: Annotated[ControlSet, Depends(get_controls)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
    format: Annotated[str, Query(pattern="^(html|md|json)$")] = "html",
) -> Response:
    """The report as ``html`` (default), ``md`` or ``json``. 409 until the run is done."""
    job = jobs.get(run_id)
    if job is not None and job.state in (JobState.QUEUED, JobState.RUNNING):
        raise HTTPException(status_code=409, detail="the assessment is not finished")
    try:
        state, _, run_dir = _status_from_disk(settings.paths.runs_dir, run_id)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail="no such assessment") from exc
    if state is not JobState.DONE:
        raise HTTPException(status_code=409, detail="the assessment is not finished")
    path = run_dir / REPORT_FILES[format]
    if not path.is_file():
        render_reports(run_dir, controls, settings.reporting, [format])
    headers = {"Content-Disposition": f'inline; filename="report-{run_id}.{format}"'}
    if format == "html":
        headers["Content-Security-Policy"] = HTML_CSP
    return Response(
        content=path.read_bytes(),
        media_type=f"{REPORT_TYPES[format]}; charset=utf-8",
        headers=headers,
    )


@router.patch(
    "/{run_id}/findings/{control_id}",
    summary="Override the status of one control (analyst decision)",
)
def override_finding(
    run_id: RunId,
    control_id: ControlId,
    body: OverrideRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    controls: Annotated[ControlSet, Depends(get_controls)],
    memory: Annotated[MemoryStore, Depends(get_memory)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> OverrideResponse:
    """Records the override, recomputes the score and the reports, and audits it."""
    if len(body.reason) > settings.api.max_override_reason_chars:
        raise HTTPException(status_code=422, detail="reason is too long")
    if len(body.analyst) > settings.api.max_override_analyst_chars:
        raise HTTPException(status_code=422, detail="analyst is too long")
    job = jobs.get(run_id)
    if job is not None and job.state in (JobState.QUEUED, JobState.RUNNING):
        raise HTTPException(status_code=409, detail="the assessment is not finished")
    try:
        _, _, run_dir = _status_from_disk(settings.paths.runs_dir, run_id)
    except ConfigError as exc:
        raise HTTPException(status_code=404, detail="no such assessment") from exc
    wanted = control_id.upper()
    if not any(c.id == wanted for c in controls.controls):
        raise HTTPException(status_code=404, detail="no such control")
    result = apply_override(
        settings, controls, run_dir, wanted, body.status, body.reason, body.analyst, memory=memory
    )
    finding = next(f for f in result.findings if f.control_id == wanted)
    return OverrideResponse(finding=finding, score=result.score)


__all__ = ["router"]
