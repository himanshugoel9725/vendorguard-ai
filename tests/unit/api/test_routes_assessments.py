"""Assessment routes end to end with the mock LLM (offline, deterministic)."""

import json
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vendorguard.api import app as app_module
from vendorguard.api.app import create_app
from vendorguard.api.routes import assessments as routes
from vendorguard.config import Settings
from vendorguard.errors import (
    BudgetExceededError,
    ConfigError,
    IngestError,
    LLMError,
    MemoryStoreError,
)
from vendorguard.utils.hashing import sha256_bytes
from vendorguard.utils.ids import make_run_id

Make = Callable[..., Settings]
SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples"
POLL_S = 15.0
CONTROLS = 25


def _sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def _files(*items: tuple[str, bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, data, "application/octet-stream")) for name, data in items]


def _settings(settings_override: Make, **api: Any) -> Settings:
    return settings_override(cache={"enabled": False}, api={"rate_limit_per_minute": 100000, **api})


def _headers(s: Settings) -> dict[str, str]:
    return {"X-API-Key": s.api.auth_key.get_secret_value()}


@pytest.fixture
def settings(settings_override: Make) -> Settings:
    return _settings(settings_override)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), headers=_headers(settings)) as c:
        yield c


def _post(client: TestClient, vendor: str, *items: tuple[str, bytes], **kw: Any) -> Any:
    return client.post("/v1/assessments", data={"vendor_id": vendor}, files=_files(*items), **kw)


def _wait(client: TestClient, run_id: str) -> dict[str, Any]:
    end = time.monotonic() + POLL_S
    while time.monotonic() < end:
        body = client.get(f"/v1/assessments/{run_id}").json()
        if body["status"] in ("done", "failed"):
            return body  # type: ignore[no-any-return]
        time.sleep(0.05)
    raise AssertionError("assessment did not finish")


def _run(client: TestClient, vendor: str = "nimbara-hr", name: str = "nimbara-hr.txt") -> str:
    r = _post(client, vendor, (name, _sample(name)))
    assert r.status_code == 202, r.text
    run_id: str = r.json()["run_id"]
    assert _wait(client, run_id)["status"] == "done"
    return run_id


def _uploads_empty(s: Settings) -> bool:
    base = s.paths.state_dir / "uploads"
    return not base.exists() or not any(base.iterdir())


# ----------------------------------------------------------------------------- lifecycle


def test_lifecycle_start_poll_result(client: TestClient, settings: Settings) -> None:
    data = _sample("nimbara-hr.txt")
    r = _post(client, "nimbara-hr", ("nimbara-hr.txt", data))
    assert r.status_code == 202
    body = r.json()
    assert set(body) == {"run_id", "status", "status_url"}
    assert body["status"] in ("queued", "running", "done")
    assert body["status_url"] == f"/v1/assessments/{body['run_id']}"
    done = _wait(client, body["run_id"])
    assert done["status"] == "done" and done["error"] is None
    assert len(done["result"]["findings"]) == CONTROLS
    assert done["result"]["run_id"] == body["run_id"]
    assert done["result"]["vendor_id"] == "nimbara-hr"


def test_run_id_is_derived_from_hashes_and_config(client: TestClient, settings: Settings) -> None:
    a, b = _sample("nimbara-hr.txt"), _sample("quillfield.txt")
    r = _post(client, "v-one", ("a.txt", a), ("b.txt", b))
    expected = make_run_id(
        "v-one",
        sorted([sha256_bytes(a), sha256_bytes(b)]),
        settings.fingerprint(),
        deterministic=settings.pipeline.deterministic_run_ids,
    )
    assert r.json()["run_id"] == expected
    _wait(client, expected)
    # same documents, other order and other names: the same run id
    r2 = _post(client, "v-one", ("z.txt", b), ("y.txt", a))
    assert r2.json()["run_id"] == expected
    _wait(client, expected)
    # another vendor id or other documents: another run id
    for other in (
        _post(client, "v-two", ("a.txt", a), ("b.txt", b)).json()["run_id"],
        _post(client, "v-one", ("a.txt", a)).json()["run_id"],
    ):
        assert other != expected
        _wait(client, other)


def test_duplicate_identical_files_count_once(client: TestClient, settings: Settings) -> None:
    data = _sample("brightdock.txt")
    r = _post(client, "bd", ("a.txt", data), ("b.txt", data))
    expected = make_run_id(
        "bd",
        [sha256_bytes(data)],
        settings.fingerprint(),
        deterministic=settings.pipeline.deterministic_run_ids,
    )
    assert r.status_code == 202 and r.json()["run_id"] == expected
    assert _wait(client, expected)["status"] == "done"


def test_uploads_are_deleted_and_audit_and_manifest_exist(
    client: TestClient, settings: Settings
) -> None:
    run_id = _run(client)
    assert _uploads_empty(settings)
    run_dir = settings.paths.runs_dir / run_id
    assert (run_dir / "audit.jsonl").stat().st_size > 0
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "done"
    assert (run_dir / "result.json").is_file()


def test_multiple_files_and_pdf(client: TestClient) -> None:
    r = _post(
        client,
        "multi",
        ("a.txt", _sample("quillfield.txt")),
        ("b.pdf", _sample("quillfield.pdf")),
    )
    assert r.status_code == 202
    assert _wait(client, r.json()["run_id"])["status"] == "done"


def test_same_run_twice_while_running_is_one_job(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _settings(settings_override)
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def fake(*args: Any, **kw: Any) -> None:
        calls.append(kw["run_id"])
        started.set()
        release.wait(10)
        raise RuntimeError("stop here")

    monkeypatch.setattr(app_module, "run_assessment", fake)
    with TestClient(create_app(s), headers=_headers(s)) as c:
        data = _sample("brightdock.txt")
        first = _post(c, "bd", ("a.txt", data)).json()
        assert started.wait(5)
        second = _post(c, "bd", ("a.txt", data)).json()
        assert first["run_id"] == second["run_id"]
        assert second["status"] == "running"
        assert _uploads_count(s) == 1  # the duplicate upload was removed
        release.set()
        assert _wait(c, first["run_id"])["status"] == "failed"
    assert calls == [first["run_id"]]
    assert _uploads_empty(s)


def _uploads_count(s: Settings) -> int:
    base = s.paths.state_dir / "uploads"
    return len(list(base.iterdir())) if base.exists() else 0


# ----------------------------------------------------------------------------- POST errors


@pytest.mark.parametrize("vendor", ["../x", "a b", "", "-lead", "x" * 65, "a/b"])
def test_bad_vendor_id_is_422(client: TestClient, settings: Settings, vendor: str) -> None:
    r = _post(client, vendor, ("a.txt", b"hello text"))
    assert r.status_code == 422
    assert _uploads_empty(settings)


def test_missing_vendor_id_is_422(client: TestClient, settings: Settings) -> None:
    r = client.post("/v1/assessments", files=_files(("a.txt", b"hello")))
    assert r.status_code == 422 and _uploads_empty(settings)


def test_no_files_is_422(client: TestClient, settings: Settings) -> None:
    r = client.post("/v1/assessments", data={"vendor_id": "v"})
    assert r.status_code == 422 and _uploads_empty(settings)


@pytest.mark.parametrize("name", ["evil.exe", "page.html", "noext", "x.txt.exe"])
def test_unsupported_extension_is_415(client: TestClient, settings: Settings, name: str) -> None:
    r = _post(client, "v", (name, b"hello"))
    assert r.status_code == 415
    assert _uploads_empty(settings)


def test_empty_filename_is_not_a_file_part(client: TestClient, settings: Settings) -> None:
    r = _post(client, "v", ("", b"hello"))
    assert r.status_code in (415, 422) and _uploads_empty(settings)


def test_pdf_without_magic_is_415(client: TestClient, settings: Settings) -> None:
    r = _post(client, "v", ("a.pdf", b"not a pdf at all"))
    assert r.status_code == 415 and _uploads_empty(settings)


def test_non_utf8_and_nul_text_are_415(client: TestClient) -> None:
    assert _post(client, "v", ("a.txt", b"\xff\xfe\xfa")).status_code == 415
    assert _post(client, "v", ("a.txt", b"ab\x00cd")).status_code == 415


def test_empty_file_is_400(client: TestClient, settings: Settings) -> None:
    r = _post(client, "v", ("a.txt", b""))
    assert r.status_code == 400 and _uploads_empty(settings)


def test_too_many_files_is_refused_and_leaves_nothing(settings_override: Make) -> None:
    s = _settings(settings_override, max_files_per_request=2)
    with TestClient(create_app(s), headers=_headers(s)) as c:
        r = _post(c, "v", *[(f"f{i}.txt", f"doc {i}".encode()) for i in range(3)])
        assert r.status_code in (400, 413)
        assert _uploads_empty(s)
        ok = _post(c, "v", *[(f"f{i}.txt", f"doc {i}".encode()) for i in range(2)])
        assert ok.status_code == 202
        _wait(c, ok.json()["run_id"])


def test_too_many_files_is_413(settings_override: Make) -> None:
    s = _settings(settings_override, max_files_per_request=2)
    with TestClient(create_app(s), headers=_headers(s)) as c:
        r = _post(c, "v", *[(f"f{i}.txt", f"doc {i}".encode()) for i in range(3)])
        assert r.status_code == 413


def test_oversize_file_is_413(settings_override: Make, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(settings_override, max_upload_mb=1)
    monkeypatch.setattr(app_module, "run_assessment", lambda *a, **k: None)  # no real 1 MB run
    limit = 1024 * 1024
    with TestClient(create_app(s), headers=_headers(s)) as c:
        too_big = _post(c, "v", ("a.txt", b"a" * (limit + 1)))
        assert too_big.status_code == 413
        assert _uploads_empty(s)
        exact = _post(c, "v", ("a.txt", b"a" * limit))
        assert exact.status_code == 202


def test_missing_or_wrong_key_is_401_and_the_route_never_runs(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[int] = []

    async def spy(*a: Any, **k: Any) -> Any:
        called.append(1)
        raise AssertionError("route ran")

    monkeypatch.setattr(routes, "read_form", spy)
    files = _files(("a.txt", b"hello"))
    r = client.post(
        "/v1/assessments", data={"vendor_id": "v"}, files=files, headers={"X-API-Key": ""}
    )
    assert r.status_code == 401
    bad = client.post(
        "/v1/assessments", data={"vendor_id": "v"}, files=files, headers={"X-API-Key": "nope"}
    )
    assert bad.status_code == 401
    assert called == [] and _uploads_empty(settings)
    assert not settings.paths.runs_dir.exists() or not any(settings.paths.runs_dir.iterdir())


def test_queue_full_is_503_with_retry_after(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _settings(settings_override, max_queued_jobs=1)
    started, release = threading.Event(), threading.Event()

    def blocked(*args: Any, **kw: Any) -> None:
        started.set()
        release.wait(10)

    monkeypatch.setattr(app_module, "run_assessment", blocked)
    with TestClient(create_app(s), headers=_headers(s)) as c:
        assert _post(c, "v", ("a.txt", b"doc one")).status_code == 202
        assert started.wait(5)
        assert _post(c, "v", ("a.txt", b"doc two")).status_code == 202  # waits (1 slot)
        before = _uploads_count(s)
        r = _post(c, "v", ("a.txt", b"doc three"))
        assert r.status_code == 503
        assert r.headers["Retry-After"].isdigit()
        assert _uploads_count(s) == before  # the refused upload folder was removed
        release.set()


# ----------------------------------------------------------------------------- GET status


def test_status_unknown_run_is_404(client: TestClient) -> None:
    r = client.get("/v1/assessments/run_000000000000")
    assert r.status_code == 404 and r.json() == {"detail": "no such assessment"}


@pytest.mark.parametrize(
    "bad",
    ["..%2F..%2Fetc", "%2e%2e", "a%2Fb", "x" * 500, "has space", "a.b", "%00", "..%5Cx"],
)
def test_status_malformed_run_id_never_traverses(client: TestClient, bad: str) -> None:
    for suffix in ("", "/report"):
        r = client.get(f"/v1/assessments/{bad}{suffix}")
        assert r.status_code in (404, 422)
        assert "root:" not in r.text and "passwd" not in r.text


def test_failed_run_shows_error_class_only(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _settings(settings_override)

    def boom(*args: Any, **kw: Any) -> None:
        raise ConfigError("SECRET-DETAIL at /home/x/file.py line 3")

    monkeypatch.setattr(app_module, "run_assessment", boom)
    with TestClient(create_app(s), headers=_headers(s)) as c:
        run_id = _post(c, "v", ("a.txt", b"hello doc")).json()["run_id"]
        body = _wait(c, run_id)
        assert body["status"] == "failed" and body["error"] == "ConfigError"
        assert body["result"] is None
        text = json.dumps(body)
        assert "SECRET" not in text and "Traceback" not in text and "/home" not in text
        # a failed run cannot be reported or overridden
        assert c.get(f"/v1/assessments/{run_id}/report").status_code == 404
        assert _uploads_empty(s)


def test_value_error_also_gives_class_name(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _settings(settings_override)

    def boom(*args: Any, **kw: Any) -> None:
        raise ValueError("private")

    monkeypatch.setattr(app_module, "run_assessment", boom)
    with TestClient(create_app(s), headers=_headers(s)) as c:
        run_id = _post(c, "v", ("a.txt", b"hello doc")).json()["run_id"]
        body = _wait(c, run_id)
        assert body["error"] == "ValueError" and "private" not in json.dumps(body)


def test_run_folder_left_running_with_no_job_is_interrupted(
    client: TestClient, settings: Settings, settings_override: Make
) -> None:
    run_id = _run(client)
    manifest_path = settings.paths.runs_dir / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "running"
    manifest_path.write_text(json.dumps(manifest))
    # a restarted server has no job for it
    with TestClient(create_app(settings), headers=_headers(settings)) as fresh:
        body = fresh.get(f"/v1/assessments/{run_id}").json()
        assert body["status"] == "failed" and body["error"] == "interrupted"
        assert body["result"] is None
        assert fresh.get(f"/v1/assessments/{run_id}/report").status_code == 409
        r = fresh.patch(
            f"/v1/assessments/{run_id}/findings/IAM-02",
            json={"status": "met", "reason": "r", "analyst": "a"},
        )
        assert r.status_code == 400  # run did not finish (ConfigError, our own message)


def test_status_of_a_done_run_after_restart(client: TestClient, settings: Settings) -> None:
    run_id = _run(client)
    with TestClient(create_app(settings), headers=_headers(settings)) as fresh:
        body = fresh.get(f"/v1/assessments/{run_id}").json()
        assert body["status"] == "done" and len(body["result"]["findings"]) == CONTROLS


# ----------------------------------------------------------------------------- GET report


def test_report_formats_and_headers(client: TestClient) -> None:
    run_id = _run(client)
    html = client.get(f"/v1/assessments/{run_id}/report")
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    csp = html.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp
    assert html.headers["content-disposition"] == f'inline; filename="report-{run_id}.html"'
    assert "nimbara" in html.text.lower()
    md = client.get(f"/v1/assessments/{run_id}/report", params={"format": "md"})
    assert md.headers["content-type"].startswith("text/markdown")
    assert md.headers["content-disposition"].endswith(f'report-{run_id}.md"')
    assert "content-security-policy" not in md.headers
    js = client.get(f"/v1/assessments/{run_id}/report", params={"format": "json"})
    assert js.headers["content-type"].startswith("application/json")
    assert js.headers["content-disposition"].endswith(f'report-{run_id}.json"')
    assert isinstance(js.json(), dict) and js.json()


def test_report_html_has_no_script_tags(client: TestClient) -> None:
    run_id = _run(client)
    html = client.get(f"/v1/assessments/{run_id}/report").text
    assert "<script" not in html.lower()
    assert not re.search(r"\son\w+\s*=", html.lower())


def test_report_errors(client: TestClient) -> None:
    assert client.get("/v1/assessments/run_000000000000/report").status_code == 404
    run_id = _run(client)
    assert (
        client.get(f"/v1/assessments/{run_id}/report", params={"format": "pdf"}).status_code == 422
    )


def test_report_and_override_are_409_while_running(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _settings(settings_override)
    started, release = threading.Event(), threading.Event()
    with TestClient(create_app(s), headers=_headers(s)) as c:
        template_id = _run(c, "template", "quillfield.txt")
        template = json.loads((s.paths.runs_dir / template_id / "manifest.json").read_text())

        def fake(settings: Settings, vendor: str, files: Any, **kw: Any) -> None:
            run_dir = settings.paths.runs_dir / kw["run_id"]  # what a real run does first
            run_dir.mkdir(parents=True, exist_ok=True)
            manifest = {**template, "run_id": kw["run_id"], "status": "running"}
            (run_dir / "manifest.json").write_text(json.dumps(manifest))
            started.set()
            release.wait(10)

        monkeypatch.setattr(app_module, "run_assessment", fake)
        run_id = _post(c, "v", ("a.txt", _sample("brightdock.txt"))).json()["run_id"]
        assert started.wait(10)
        assert c.get(f"/v1/assessments/{run_id}").json()["status"] == "running"
        assert c.get(f"/v1/assessments/{run_id}/report").status_code == 409
        r = c.patch(
            f"/v1/assessments/{run_id}/findings/IAM-02",
            json={"status": "met", "reason": "r", "analyst": "a"},
        )
        assert r.status_code == 409
        release.set()
        _wait(c, run_id)


@pytest.mark.parametrize("fmt", ["html", "md", "json"])
def test_missing_report_file_is_rerendered(
    client: TestClient, settings: Settings, fmt: str
) -> None:
    run_id = _run(client)
    path = settings.paths.runs_dir / run_id / f"report.{fmt}"
    assert path.is_file()
    path.unlink()
    r = client.get(f"/v1/assessments/{run_id}/report", params={"format": fmt})
    assert r.status_code == 200 and r.content
    assert path.is_file()


def test_same_documents_give_the_same_findings_and_score(
    client: TestClient, settings: Settings
) -> None:
    run_id = _run(client)
    first = client.get(f"/v1/assessments/{run_id}").json()["result"]
    shutil.rmtree(settings.paths.runs_dir / run_id)
    assert _run(client) == run_id
    second = client.get(f"/v1/assessments/{run_id}").json()["result"]
    assert second["findings"] == first["findings"] and second["score"] == first["score"]


# ----------------------------------------------------------------------------- PATCH override


def _override(client: TestClient, run_id: str, control: str = "IAM-02", **body: Any) -> Any:
    payload = {"status": "met", "reason": "checked the evidence", "analyst": "ana", **body}
    return client.patch(f"/v1/assessments/{run_id}/findings/{control}", json=payload)


def test_override_changes_score_reports_and_memory(client: TestClient, settings: Settings) -> None:
    run_id = _run(client)
    before = client.get(f"/v1/assessments/{run_id}").json()["result"]
    start = next(f for f in before["findings"] if f["control_id"] == "IAM-04")
    new_status = "not_met" if start["status"] != "not_met" else "met"
    r = _override(client, run_id, "IAM-04", status=new_status)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["finding"]["control_id"] == "IAM-04"
    assert body["finding"]["override"]["new_status"] == new_status
    assert body["finding"]["override"]["analyst"] == "ana"
    assert body["finding"]["status"] == start["status"]  # the system's own status is kept
    assert body["score"] != before["score"]
    after = client.get(f"/v1/assessments/{run_id}").json()["result"]
    assert after["score"] == body["score"]
    md = client.get(f"/v1/assessments/{run_id}/report", params={"format": "md"}).text
    assert "IAM-04" in md
    stored = client.app.state.memory.get_assessment(run_id)  # type: ignore[attr-defined]
    assert stored is not None and stored.score.overall == body["score"]["overall"]
    audit = (settings.paths.runs_dir / run_id / "audit.jsonl").read_text()
    assert audit.count("analyst_override") == 1


def test_control_id_is_case_insensitive(client: TestClient) -> None:
    run_id = _run(client)
    r = _override(client, run_id, "iam-02")
    assert r.status_code == 200 and r.json()["finding"]["control_id"] == "IAM-02"


def test_second_override_replaces_the_first(client: TestClient, settings: Settings) -> None:
    run_id = _run(client)
    _override(client, run_id, "IAM-02", status="not_met", reason="first", analyst="a1")
    r = _override(client, run_id, "IAM-02", status="met", reason="second", analyst="a2")
    assert r.json()["finding"]["override"]["reason"] == "second"
    result = client.get(f"/v1/assessments/{run_id}").json()["result"]
    f = next(x for x in result["findings"] if x["control_id"] == "IAM-02")
    assert f["override"]["new_status"] == "met" and f["override"]["analyst"] == "a2"
    audit = (settings.paths.runs_dir / run_id / "audit.jsonl").read_text()
    assert audit.count("analyst_override") == 2  # the log keeps both


def test_override_error_statuses(client: TestClient) -> None:
    run_id = _run(client)
    assert _override(client, run_id, "ZZZ-99").status_code == 404
    assert _override(client, "run_000000000000").status_code == 404
    for bad in ("../x", "IAM", "IAM-2", "1AM-02", "IAM-02x", "I-02"):
        assert _override(client, run_id, bad).status_code in (404, 422), bad
    assert _override(client, run_id, "IAM-02", reason="").status_code == 422
    assert _override(client, run_id, "IAM-02", analyst="").status_code == 422
    assert _override(client, run_id, "IAM-02", reason="x" * 1001).status_code == 422
    assert _override(client, run_id, "IAM-02", analyst="x" * 101).status_code == 422
    assert _override(client, run_id, "IAM-02", status="needs_human_review").status_code == 422
    assert _override(client, run_id, "IAM-02", status="bogus").status_code == 422
    assert _override(client, run_id, "IAM-02", reason="   ").status_code == 400
    assert _override(client, run_id, "IAM-02", reason="x" * 1000).status_code == 200


# ----------------------------------------------------------------------------- error mapping


@pytest.mark.parametrize(
    ("exc", "status", "detail"),
    [
        (IngestError("INTERNAL-PATH /tmp/x"), 422, "a document could not be read"),
        (BudgetExceededError("INTERNAL $1.23"), 429, "the cost budget of this request is used up"),
        (LLMError("INTERNAL sk-abc"), 502, "a model provider failed"),
        (MemoryStoreError("INTERNAL sql"), 500, "the memory store failed"),
    ],
)
def test_error_mapping_uses_fixed_messages(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    status: int,
    detail: str,
) -> None:
    run_id = _run(client)

    def raiser(*a: Any, **k: Any) -> Any:
        raise exc

    monkeypatch.setattr(routes, "apply_override", raiser)
    r = _override(client, run_id)
    assert r.status_code == status and r.json() == {"detail": detail}
    assert "INTERNAL" not in r.text


def test_memory_store_error_never_leaks_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _run(client)

    def raiser(*a: Any, **k: Any) -> Any:
        raise MemoryStoreError("INTERNAL sql")

    monkeypatch.setattr(routes, "apply_override", raiser)
    r = _override(client, run_id)
    assert r.status_code in (500, 502) and "INTERNAL" not in r.text


def test_config_error_message_is_shown_as_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _run(client)

    def raiser(*a: Any, **k: Any) -> Any:
        raise ConfigError("our own words")

    monkeypatch.setattr(routes, "apply_override", raiser)
    r = _override(client, run_id)
    assert r.status_code == 400 and r.json() == {"detail": "our own words"}


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    run_id = _run(client)
    r = _override(client, run_id, reason="", analyst="SECRET-NAME")
    assert r.status_code == 422 and "SECRET-NAME" not in r.text
