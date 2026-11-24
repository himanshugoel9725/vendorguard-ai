"""RunContext: everything the per-control cascade needs, built once per run."""

import threading
from dataclasses import dataclass, field
from pathlib import Path

from vendorguard.agents.intake import IntakeAgent
from vendorguard.agents.mapper import MapperAgent
from vendorguard.agents.reporter import ReporterAgent
from vendorguard.agents.reviewer import ReviewerAgent
from vendorguard.config import Settings
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.decider import Decider
from vendorguard.interfaces.embedder import Embedder
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.verification.citation_check import CitationChecker


@dataclass(frozen=True)
class RunContext:
    """Shared, read-only collaborators of one run. ``abort`` stops workers after a failure."""

    settings: Settings
    run_id: str
    run_dir: Path
    audit: AuditSink
    decider: Decider
    embedder: Embedder
    cost: CostTracker
    intake: IntakeAgent
    mapper: MapperAgent
    reviewer: ReviewerAgent
    reporter: ReporterAgent
    citation: CitationChecker
    abort: threading.Event = field(default_factory=threading.Event)


__all__ = ["RunContext"]
