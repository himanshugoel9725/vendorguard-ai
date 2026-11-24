"""Append-only JSONL audit log of one run: one line per recorded step, increasing ``seq``."""

import json
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from vendorguard.errors import ConfigError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.decision import Decision
from vendorguard.utils.timeutil import utcnow


def read_audit_log(path: Path) -> list[AuditEvent]:
    """Read and validate a log file; ``seq`` must start anywhere but strictly increase."""
    if not path.is_file():
        return []
    events: list[AuditEvent] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = AuditEvent.model_validate(json.loads(line))
        except (ValueError, ValidationError) as exc:
            raise ConfigError(f"audit log {path.name} line {number} is damaged") from exc
        if events and event.seq <= events[-1].seq:
            raise ConfigError(f"audit log {path.name} line {number}: seq does not increase")
        events.append(event)
    return events


class AuditLog:
    """Implements ``AuditSink``: adds run ID, sequence number and time, then appends a line.

    Thread-safe. Opening an existing log continues after its last ``seq``. Events hold hashes
    and counts only, never document text or secrets. ``on_event`` (for example the metrics)
    sees every stored event.
    """

    def __init__(
        self,
        path: Path,
        run_id: str,
        on_event: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.path = path
        self.run_id = run_id
        self._on_event = on_event
        self._lock = threading.Lock()
        existing = read_audit_log(path)
        self._next_seq = existing[-1].seq + 1 if existing else 0
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        stage: str,
        actor: str,
        input_hash: str,
        output_hash: str,
        tokens_in: int,
        tokens_out: int,
        usd: float,
        latency_ms: float,
        cached: bool,
        control_id: str | None = None,
        decision: Decision | None = None,
    ) -> AuditEvent:
        """Store the event (one flushed line) and return it."""
        with self._lock:
            event = AuditEvent(
                run_id=self.run_id,
                seq=self._next_seq,
                ts=utcnow(),
                stage=stage,
                actor=actor,
                control_id=control_id,
                input_hash=input_hash,
                output_hash=output_hash,
                decision=decision,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                usd=usd,
                latency_ms=latency_ms,
                cached=cached,
            )
            line = json.dumps(event.model_dump(mode="json"), sort_keys=True, ensure_ascii=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._next_seq += 1
        if self._on_event is not None:
            self._on_event(event)
        return event

    def events(self) -> list[AuditEvent]:
        """All events stored so far, read back from the file."""
        return read_audit_log(self.path)


__all__ = ["AuditLog", "read_audit_log"]
