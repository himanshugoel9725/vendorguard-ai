"""SQLite memory store: the system of record for assessments, findings and overrides."""

import sqlite3
import threading
from pathlib import Path

from pydantic import ValidationError

from vendorguard.errors import MemoryStoreError
from vendorguard.models.run import AssessmentResult, AssessmentSummary, VendorSummary
from vendorguard.models.score import RiskBand
from vendorguard.observability.run_manifest import result_hash
from vendorguard.utils.jsonio import canonical_json

SCHEMA = Path(__file__).with_name("schema.sql")


class SqliteMemoryStore:
    """Implements ``MemoryStore``. One connection guarded by a lock (WAL, parameterised SQL).

    ``get_assessment`` returns exactly what was saved: the canonical JSON round-trips, so the
    result hash is identical after a save and a load.
    """

    def __init__(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(SCHEMA.read_text(encoding="utf-8"))
        except (OSError, sqlite3.Error) as exc:
            raise MemoryStoreError(
                f"cannot open the memory database: {type(exc).__name__}"
            ) from exc
        self._lock = threading.Lock()

    def save_assessment(self, result: AssessmentResult) -> None:
        """Store (or replace) the result of one run, with its findings and overrides."""
        body = canonical_json(result.model_dump(mode="json"))
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO vendors(vendor_id, name) VALUES (?, ?) "
                "ON CONFLICT(vendor_id) DO UPDATE SET name = excluded.name",
                (result.vendor_id, result.profile.vendor_name),
            )
            self._db.execute("DELETE FROM assessments WHERE run_id = ?", (result.run_id,))
            self._db.execute(
                "INSERT INTO assessments(run_id, vendor_id, created_at, overall, band, "
                "result_hash, result_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    result.run_id,
                    result.vendor_id,
                    result.created_at.isoformat(),
                    result.score.overall,
                    result.score.band.value,
                    result_hash(result),
                    body,
                ),
            )
            for f in result.findings:
                self._db.execute(
                    "INSERT INTO findings(run_id, control_id, status, effective_status) "
                    "VALUES (?, ?, ?, ?)",
                    (result.run_id, f.control_id, f.status.value, f.effective_status.value),
                )
                if f.override is not None:
                    o = f.override
                    self._db.execute(
                        "INSERT INTO overrides(run_id, control_id, analyst, new_status, "
                        "reason, at) VALUES (?, ?, ?, ?, ?, ?)",
                        (result.run_id, f.control_id, o.analyst, o.new_status.value, o.reason,
                         o.at.isoformat()),
                    )  # fmt: skip

    def get_assessment(self, run_id: str) -> AssessmentResult | None:
        """The stored result of a run, or ``None`` if unknown."""
        with self._lock:
            row = self._db.execute(
                "SELECT result_json FROM assessments WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def latest_assessment(
        self, vendor_id: str, *, exclude_run_id: str | None = None
    ) -> AssessmentResult | None:
        """The vendor's most recent result (ties by run id), optionally ignoring one run."""
        with self._lock:
            row = self._db.execute(
                "SELECT result_json FROM assessments WHERE vendor_id = ? AND run_id IS NOT ? "
                "ORDER BY created_at DESC, run_id DESC LIMIT 1",
                (vendor_id, exclude_run_id),
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_assessments(self, vendor_id: str) -> list[AssessmentSummary]:
        """The vendor's history, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT run_id, vendor_id, created_at, overall, band FROM assessments "
                "WHERE vendor_id = ? ORDER BY created_at DESC, run_id DESC",
                (vendor_id,),
            ).fetchall()
        return [
            AssessmentSummary(
                run_id=r[0], vendor_id=r[1], created_at=r[2], overall=r[3], band=RiskBand(r[4])
            )
            for r in rows
        ]

    def list_vendors(self) -> list[VendorSummary]:
        """All vendors by ID, with their number of runs and the band of the latest one."""
        with self._lock:
            rows = self._db.execute(
                "SELECT v.vendor_id, v.name, COUNT(a.run_id), "
                "(SELECT band FROM assessments WHERE vendor_id = v.vendor_id "
                " ORDER BY created_at DESC, run_id DESC LIMIT 1) "
                "FROM vendors v LEFT JOIN assessments a ON a.vendor_id = v.vendor_id "
                "GROUP BY v.vendor_id ORDER BY v.vendor_id"
            ).fetchall()
        return [
            VendorSummary(
                vendor_id=r[0], name=r[1], runs=r[2], latest_band=RiskBand(r[3]) if r[3] else None
            )
            for r in rows
        ]

    def close(self) -> None:
        """Close the database."""
        with self._lock:
            self._db.close()

    @staticmethod
    def _load(text: str) -> AssessmentResult:
        try:
            return AssessmentResult.model_validate_json(text)
        except ValidationError as exc:
            raise MemoryStoreError("a stored assessment is damaged") from exc


__all__ = ["SqliteMemoryStore"]
