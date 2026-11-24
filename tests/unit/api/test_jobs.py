"""JobRegistry tests with a fake ``work`` function (no pipeline, no network)."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.api.jobs import Job, JobRegistry, JobState, QueueFull

WAIT_S = 5.0


def _job(tmp_path: Path, name: str, vendor: str = "v") -> Job:
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    (folder / "f.txt").write_text("x")
    return Job(run_id=name, vendor_id=vendor, folder=folder, files=[folder / "f.txt"])


def _wait_for(predicate: Callable[[], bool]) -> None:
    end = time.monotonic() + WAIT_S
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached in time")


def _done(reg: JobRegistry, run_id: str) -> bool:
    job = reg.get(run_id)
    return job is not None and job.state in (JobState.DONE, JobState.FAILED)


@pytest.fixture
def registries() -> list[JobRegistry]:
    made: list[JobRegistry] = []
    return made


def _make(
    registries: list[JobRegistry], work: Callable[[Job], None], q: int = 5, fin: int = 50
) -> JobRegistry:
    reg = JobRegistry(work, q, fin)
    registries.append(reg)
    return reg


@pytest.fixture(autouse=True)
def _cleanup(registries: list[JobRegistry]) -> object:
    yield
    for reg in registries:
        reg.close()


def test_state_goes_queued_running_done(tmp_path: Path, registries: list[JobRegistry]) -> None:
    started, release = threading.Event(), threading.Event()

    def work(job: Job) -> None:
        started.set()
        assert release.wait(WAIT_S)

    reg = _make(registries, work)
    job, created = reg.submit(_job(tmp_path, "a"))
    assert created is True and job.run_id == "a"
    assert started.wait(WAIT_S)
    assert reg.get("a") is not None and reg.get("a").state is JobState.RUNNING  # type: ignore[union-attr]
    release.set()
    _wait_for(lambda: _done(reg, "a"))
    final = reg.get("a")
    assert final is not None and final.state is JobState.DONE and final.error is None


def test_a_waiting_job_is_queued(tmp_path: Path, registries: list[JobRegistry]) -> None:
    started, release = threading.Event(), threading.Event()

    def work(job: Job) -> None:
        started.set()
        release.wait(WAIT_S)

    reg = _make(registries, work)
    reg.submit(_job(tmp_path, "a"))
    assert started.wait(WAIT_S)
    second, _ = reg.submit(_job(tmp_path, "b"))
    assert second.state is JobState.QUEUED
    release.set()
    _wait_for(lambda: _done(reg, "b"))


def test_exception_gives_failed_with_class_name_only(
    tmp_path: Path, registries: list[JobRegistry]
) -> None:
    def work(job: Job) -> None:
        raise ValueError("secret-text /etc/passwd sk-123")

    reg = _make(registries, work)
    reg.submit(_job(tmp_path, "a"))
    _wait_for(lambda: _done(reg, "a"))
    job = reg.get("a")
    assert job is not None
    assert job.state is JobState.FAILED
    assert job.error == "ValueError"
    assert "secret" not in repr(job.error)


def test_failure_does_not_stop_the_worker(tmp_path: Path, registries: list[JobRegistry]) -> None:
    def work(job: Job) -> None:
        if job.run_id == "bad":
            raise RuntimeError("boom")

    reg = _make(registries, work)
    reg.submit(_job(tmp_path, "bad"))
    reg.submit(_job(tmp_path, "good"))
    _wait_for(lambda: _done(reg, "good"))
    assert reg.get("good").state is JobState.DONE  # type: ignore[union-attr]
    assert reg.get("bad").state is JobState.FAILED  # type: ignore[union-attr]


def test_one_worker_jobs_never_overlap(tmp_path: Path, registries: list[JobRegistry]) -> None:
    lock = threading.Lock()
    active = 0
    peak = 0
    gate = threading.Event()

    def work(job: Job) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        gate.wait(WAIT_S)
        time.sleep(0.01)
        with lock:
            active -= 1

    reg = _make(registries, work)
    for n in ("a", "b", "c"):
        reg.submit(_job(tmp_path, n))
    gate.set()
    for n in ("a", "b", "c"):
        _wait_for(lambda n=n: _done(reg, n))  # type: ignore[misc]
    assert peak == 1


def test_same_run_while_queued_or_running_is_not_created_again(
    tmp_path: Path, registries: list[JobRegistry]
) -> None:
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def work(job: Job) -> None:
        calls.append(job.run_id)
        started.set()
        release.wait(WAIT_S)

    reg = _make(registries, work)
    first, c1 = reg.submit(_job(tmp_path, "a"))
    assert started.wait(WAIT_S)
    again, c2 = reg.submit(_job(tmp_path, "a"))  # running
    assert (c1, c2) == (True, False) and again is first
    queued, c3 = reg.submit(_job(tmp_path, "b"))
    dup, c4 = reg.submit(_job(tmp_path, "b"))  # queued
    assert c3 is True and c4 is False and dup is queued
    release.set()
    _wait_for(lambda: _done(reg, "b"))
    assert calls == ["a", "b"]


def test_a_finished_run_can_be_submitted_again(
    tmp_path: Path, registries: list[JobRegistry]
) -> None:
    reg = _make(registries, lambda job: None)
    reg.submit(_job(tmp_path, "a"))
    _wait_for(lambda: _done(reg, "a"))
    again, created = reg.submit(_job(tmp_path, "a"))
    assert created is True and again.state in (JobState.QUEUED, JobState.RUNNING, JobState.DONE)


def test_queue_full_counts_only_waiting_jobs(tmp_path: Path, registries: list[JobRegistry]) -> None:
    started, release = threading.Event(), threading.Event()

    def work(job: Job) -> None:
        started.set()
        release.wait(WAIT_S)

    reg = _make(registries, work, q=2)
    reg.submit(_job(tmp_path, "run"))
    assert started.wait(WAIT_S)  # running: does not count
    reg.submit(_job(tmp_path, "w1"))
    reg.submit(_job(tmp_path, "w2"))
    with pytest.raises(QueueFull):
        reg.submit(_job(tmp_path, "w3"))
    assert reg.get("w3") is None
    release.set()
    _wait_for(lambda: _done(reg, "w2"))


def test_zero_queue_allows_nothing_to_wait(tmp_path: Path, registries: list[JobRegistry]) -> None:
    reg = _make(registries, lambda job: None, q=0)
    with pytest.raises(QueueFull):
        reg.submit(_job(tmp_path, "a"))


def test_finished_jobs_are_trimmed(tmp_path: Path, registries: list[JobRegistry]) -> None:
    reg = _make(registries, lambda job: None, fin=2)
    for n in ("a", "b", "c", "d"):
        reg.submit(_job(tmp_path, n))
        _wait_for(lambda n=n: _done(reg, n))  # type: ignore[misc]
    # trimming runs on submit, before the new job finishes: only the oldest finished job is gone
    assert reg.get("a") is None
    assert all(reg.get(n) is not None for n in ("b", "c", "d"))
    reg.submit(_job(tmp_path, "e"))
    _wait_for(lambda: _done(reg, "e"))
    assert reg.get("b") is None and reg.get("c") is not None and reg.get("e") is not None


def test_get_unknown_is_none(registries: list[JobRegistry]) -> None:
    reg = _make(registries, lambda job: None)
    assert reg.get("nope") is None


def test_close_deletes_upload_folders_of_queued_jobs_and_cancels_them(
    tmp_path: Path, registries: list[JobRegistry]
) -> None:
    started, release = threading.Event(), threading.Event()
    ran: list[str] = []

    def work(job: Job) -> None:
        ran.append(job.run_id)
        started.set()
        release.wait(WAIT_S)

    reg = _make(registries, work)
    running = _job(tmp_path, "run")
    queued = _job(tmp_path, "queued")
    reg.submit(running)
    assert started.wait(WAIT_S)
    reg.submit(queued)
    reg.close()
    assert not queued.folder.exists()
    assert running.folder.exists()  # the worker deletes its own folder
    release.set()
    time.sleep(0.1)
    assert ran == ["run"]  # the queued job never started


def test_concurrent_submits_all_finish_in_serial_order(
    tmp_path: Path, registries: list[JobRegistry]
) -> None:
    order: list[str] = []
    active = 0
    overlap = False
    lock = threading.Lock()

    def work(job: Job) -> None:
        nonlocal active, overlap
        with lock:
            active += 1
            overlap = overlap or active > 1
        order.append(job.run_id)
        time.sleep(0.002)
        with lock:
            active -= 1

    reg = _make(registries, work, q=50)
    names = [f"j{i:02d}" for i in range(20)]
    jobs = [_job(tmp_path, n) for n in names]
    barrier = threading.Barrier(len(jobs))
    results: list[tuple[Job, bool]] = []

    def submit(j: Job) -> None:
        barrier.wait(WAIT_S)
        r = reg.submit(j)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=submit, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT_S)
    assert len(results) == 20 and all(created for _, created in results)
    for n in names:
        _wait_for(lambda n=n: _done(reg, n))  # type: ignore[misc]
    assert sorted(order) == names and len(order) == 20  # none lost, none doubled
    assert overlap is False
