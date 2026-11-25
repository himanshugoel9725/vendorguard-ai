"""HTTP client of the VendorGuard REST API for the UI. It never imports server code.

Every answer is validated with the same Pydantic models the API serialises. Errors become
``UiApiError`` carrying the API's own (fixed, safe) message; the API key is never part of a message.
"""

from collections.abc import Sequence
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import SecretStr, ValidationError

from vendorguard.models._base import ContractModel
from vendorguard.models.finding import ControlFinding, DraftStatus
from vendorguard.models.run import Answer, AssessmentResult, AssessmentSummary, VendorSummary
from vendorguard.models.score import RiskScore

MAX_DETAIL_CHARS = 300  # an error message longer than this is cut
ReportFormat = Literal["html", "md", "json"]
RunPhase = Literal["queued", "running", "done", "failed"]


class UiApiError(Exception):
    """The API refused the request or could not be reached. ``status`` is 0 for no answer."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class RunView(ContractModel):
    """Where an assessment is (``GET /v1/assessments/{run_id}``)."""

    run_id: str
    status: RunPhase
    error: str | None = None
    result: AssessmentResult | None = None


class OverrideOutcome(ContractModel):
    """The control after an analyst override and the recomputed score."""

    finding: ControlFinding
    score: RiskScore


def _detail(response: httpx.Response) -> str:
    """The API's message for a refused request (never the request body or the key)."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # 422: a list of {loc, msg, type}
        detail = "; ".join(
            str(item.get("msg", "invalid")) for item in detail if isinstance(item, dict)
        )
    if not isinstance(detail, str) or not detail:
        detail = f"the API answered HTTP {response.status_code}"
    return detail[:MAX_DETAIL_CHARS]


class ApiClient:
    """One method per API route the UI uses."""

    def __init__(
        self,
        base_url: str,
        key: SecretStr,
        timeout_s: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": key.get_secret_value()}
        self._client = client or httpx.Client(timeout=timeout_s)
        self.base_url = self._base

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(
                method, f"{self._base}{path}", headers=self._headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise UiApiError(0, f"cannot reach the API at {self._base}") from exc
        if response.status_code >= 400:
            raise UiApiError(response.status_code, _detail(response))
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return self._request(method, path, **kwargs).json()
        except ValueError as exc:
            raise UiApiError(0, "the API sent an unreadable answer") from exc

    def health(self) -> bool:
        """True if the API answers ``/health`` (no key needed)."""
        try:
            return self._client.get(f"{self._base}/health").status_code == 200
        except httpx.HTTPError:
            return False

    def start_assessment(self, vendor_id: str, files: Sequence[tuple[str, bytes]]) -> str:
        """Upload ``(name, bytes)`` files for ``vendor_id``; returns the run id (202)."""
        multipart = [("files", (name, data)) for name, data in files]
        body = self._json("POST", "/v1/assessments", data={"vendor_id": vendor_id}, files=multipart)
        return str(body["run_id"])

    def get_run(self, run_id: str) -> RunView:
        """Status of a run, with the result once it is done."""
        return self._validated(RunView, self._json("GET", f"/v1/assessments/{quote(run_id)}"))

    def get_report(self, run_id: str, fmt: ReportFormat) -> bytes:
        """The rendered report of a finished run."""
        path = f"/v1/assessments/{quote(run_id)}/report"
        return self._request("GET", path, params={"format": fmt}).content

    def override(
        self, run_id: str, control_id: str, status: DraftStatus, reason: str, analyst: str
    ) -> OverrideOutcome:
        """Record an analyst decision for one control."""
        path = f"/v1/assessments/{quote(run_id)}/findings/{quote(control_id)}"
        body = {"status": status.value, "reason": reason, "analyst": analyst}
        return self._validated(OverrideOutcome, self._json("PATCH", path, json=body))

    def vendors(self) -> list[VendorSummary]:
        """Vendors with their number of runs and latest band."""
        return [self._validated(VendorSummary, item) for item in self._json("GET", "/v1/vendors")]

    def history(self, vendor_id: str) -> list[AssessmentSummary]:
        """A vendor's stored assessments, newest first."""
        data = self._json("GET", f"/v1/vendors/{quote(vendor_id)}/history")
        return [self._validated(AssessmentSummary, item) for item in data]

    def ask(self, vendor_id: str, question: str) -> Answer:
        """A question about a vendor's history."""
        path = f"/v1/vendors/{quote(vendor_id)}/ask"
        return self._validated(Answer, self._json("POST", path, json={"question": question}))

    @staticmethod
    def _validated[T: ContractModel](model: type[T], data: Any) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise UiApiError(0, "the API sent an answer this UI does not understand") from exc


__all__ = ["ApiClient", "OverrideOutcome", "ReportFormat", "RunView", "UiApiError"]
