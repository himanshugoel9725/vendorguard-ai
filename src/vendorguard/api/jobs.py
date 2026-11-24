"""In-process job registry: one worker thread runs assessments one after another.

Only QUEUED and RUNNING jobs matter for correctness; the outcome of a finished run lives on disk
(run folder, manifest) and in the memory store. The last ``max_finished`` finished jobs are kept
so a client can see the error class of a failed run.
"""

import logging
import shutil
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)


class JobState(StrEnum):
    """Lifecycle of an API assessment."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class QueueFull(Exception):
    """Too many assessments are waiting."""


@dataclass
class Job:
    """One assessment request. ``folder`` holds the uploaded files and is deleted afterwards."""

    run_id: str
    vendor_id: str
    folder: Path
    files: list[Path] = field(default_factory=list)
    state: JobState = JobState.QUEUED
    error: str | None = None  # the exception CLASS only, never its text


class JobRegistry:
    """Single worker, bounded queue, idempotent per run ID."""

    def __init__(self, work: Callable[[Job], None], max_queued: int, max_finished: int) -> None:
        self._work = work
        self._max_queued = max_queued
        self._max_finished = max_finished
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vg-job")
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()

    def submit(self, job: Job) -> tuple[Job, bool]:
        """Queue ``job``. Returns ``(job, created)``: if the same run is already queued or
        running, that job comes back with ``created=False`` (and the new upload is discarded by
        the caller). Raises ``QueueFull`` when ``max_queued`` jobs are already waiting."""
        with self._lock:
            known = self._jobs.get(job.run_id)
            if known is not None and known.state in (JobState.QUEUED, JobState.RUNNING):
                return known, False
            waiting = sum(1 for j in self._jobs.values() if j.state is JobState.QUEUED)
            if waiting >= self._max_queued:
                raise QueueFull
            self._jobs[job.run_id] = job
            self._jobs.move_to_end(job.run_id)
            self._trim()
        self._pool.submit(self._run, job)
        return job, True

    def get(self, run_id: str) -> Job | None:
        """The job of a run, if this process still remembers it."""
        with self._lock:
            return self._jobs.get(run_id)

    def close(self) -> None:
        """Stop accepting work; queued jobs are dropped and their uploads deleted."""
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            for job in self._jobs.values():
                if job.state is JobState.QUEUED:
                    shutil.rmtree(job.folder, ignore_errors=True)

    def _run(self, job: Job) -> None:
        with self._lock:
            job.state = JobState.RUNNING
        try:
            self._work(job)
        except Exception as exc:
            log.error("job %s failed: %s", job.run_id, type(exc).__name__)
            with self._lock:
                job.state, job.error = JobState.FAILED, type(exc).__name__
        else:
            with self._lock:
                job.state = JobState.DONE

    def _trim(self) -> None:
        finished = [r for r, j in self._jobs.items() if j.state in (JobState.DONE, JobState.FAILED)]
        for run_id in finished[: max(len(finished) - self._max_finished, 0)]:
            del self._jobs[run_id]


__all__ = ["Job", "JobRegistry", "JobState", "QueueFull"]
