"""Vendor routes (list, history, ask), key enforcement, OpenAPI and app lifespan."""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vendorguard.api.app import create_app
from vendorguard.api.routes import vendors as vendor_routes
from vendorguard.config import Settings
from vendorguard.errors import BudgetExceededError, ConfigError, LLMError

Make = Callable[..., Settings]
SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples"
POLL_S = 15.0
CONTROLS = 25


def _headers(s: Settings) -> dict[str, str]:
    return {"X-API-Key": s.api.auth_key.get_secret_value()}


@pytest.fixture
def settings(settings_override: Make) -> Settings:
    return settings_override(cache={"enabled": False}, api={"rate_limit_per_minute": 100000})


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), headers=_headers(settings)) as c:
        yield c


def _run(client: TestClient, vendor: str, sample: str) -> str:
    files = [("files", (sample, (SAMPLES / sample).read_bytes(), "text/plain"))]
    r = client.post("/v1/assessments", data={"vendor_id": vendor}, files=files)
    assert r.status_code == 202, r.text
    run_id: str = r.json()["run_id"]
    end = time.monotonic() + POLL_S
    while time.monotonic() < end:
        status = client.get(f"/v1/assessments/{run_id}").json()["status"]
        if status == "done":
            return run_id
        assert status != "failed"
        time.sleep(0.05)
    raise AssertionError("assessment did not finish")


@pytest.fixture
def two_runs(client: TestClient) -> tuple[str, str]:
    y1 = _run(client, "nimbara-hr", "nimbara-hr.txt")
    y2 = _run(client, "nimbara-hr", "nimbara-hr-y2.txt")
    return y1, y2


# ----------------------------------------------------------------------------- list / history


def test_vendor_list_is_empty_then_has_the_vendor(client: TestClient) -> None:
    assert client.get("/v1/vendors").json() == []
    _run(client, "nimbara-hr", "nimbara-hr.txt")
    rows = client.get("/v1/vendors").json()
    assert len(rows) == 1
    assert rows[0]["vendor_id"] == "nimbara-hr" and rows[0]["runs"] == 1
    assert rows[0]["latest_band"] in ("low", "medium", "high", "critical")


def test_vendor_list_is_sorted_by_id(client: TestClient) -> None:
    _run(client, "quillfield", "quillfield.txt")
    _run(client, "brightdock", "brightdock.txt")
    ids = [v["vendor_id"] for v in client.get("/v1/vendors").json()]
    assert ids == sorted(ids) == ["brightdock", "quillfield"]


def test_history_newest_first(client: TestClient, two_runs: tuple[str, str]) -> None:
    y1, y2 = two_runs
    assert y1 != y2
    history = client.get("/v1/vendors/nimbara-hr/history").json()
    assert [h["run_id"] for h in history] == [y2, y1]
    assert all(h["vendor_id"] == "nimbara-hr" for h in history)
    assert client.get("/v1/vendors").json()[0]["runs"] == 2


def test_history_unknown_vendor_is_404(client: TestClient) -> None:
    r = client.get("/v1/vendors/nobody/history")
    assert r.status_code == 404 and r.json() == {"detail": "no such vendor"}


@pytest.mark.parametrize("bad", ["-lead", "a b", "x" * 65, "a%2Fb", "..%2F..", ".hidden", "a$b"])
def test_bad_vendor_id_is_422_or_404(client: TestClient, bad: str) -> None:
    for r in (
        client.get(f"/v1/vendors/{bad}/history"),
        client.post(f"/v1/vendors/{bad}/ask", json={"question": "hi"}),
    ):
        assert r.status_code in (404, 422)
    assert client.get("/v1/vendors/-lead/history").status_code == 422


# ----------------------------------------------------------------------------- ask


def test_ask_what_changed(client: TestClient, two_runs: tuple[str, str]) -> None:
    y1, y2 = two_runs
    r = client.post("/v1/vendors/nimbara-hr/ask", json={"question": "What changed for nimbara-hr?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert y1 in body["text"] and y2 in body["text"]
    assert sorted(body["cited_run_ids"]) == sorted([y1, y2])
    cited = set(body["cited_control_ids"])
    assert {"IAM-04", "PEO-02", "RES-03", "OPS-02"} <= cited
    resolved = body["text"].split("Resolved gaps:")[1]
    new = body["text"].split("New gaps:")[1].split("Resolved gaps:")[0]
    for control in ("IAM-04", "PEO-02", "RES-03"):
        assert control in resolved
    assert "OPS-02" in new
    assert body["provider"]


def test_ask_cited_ids_exist(client: TestClient, two_runs: tuple[str, str]) -> None:
    body = client.post(
        "/v1/vendors/nimbara-hr/ask", json={"question": "What is the status of IAM-04?"}
    ).json()
    known = {f.control_id for f in client.app.state.memory.get_assessment(two_runs[1]).findings}  # type: ignore[attr-defined]
    assert set(body["cited_control_ids"]) <= known
    assert set(body["cited_run_ids"]) <= set(two_runs)


def test_ask_is_deterministic(client: TestClient, two_runs: tuple[str, str]) -> None:
    q = {"question": "What changed for nimbara-hr?"}
    a = client.post("/v1/vendors/nimbara-hr/ask", json=q).json()
    b = client.post("/v1/vendors/nimbara-hr/ask", json=q).json()
    assert a == b


def test_ask_unknown_vendor_gives_the_fixed_answer(client: TestClient) -> None:
    r = client.post("/v1/vendors/nobody/ask", json={"question": "What changed?"})
    assert r.status_code == 200
    assert r.json()["text"].startswith("No assessments")
    assert r.json()["cited_run_ids"] == [] and r.json()["cited_control_ids"] == []


def test_ask_question_validation(client: TestClient, settings: Settings) -> None:
    url = "/v1/vendors/nimbara-hr/ask"
    assert client.post(url, json={"question": ""}).status_code == 422
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"question": "x" * 2001}).status_code == 400
    assert client.post(url, json={"question": 5}).status_code == 422
    limit = settings.memory.ask_max_question_chars
    too_long = client.post(url, json={"question": "a" * (limit + 1)})
    assert too_long.status_code == 400
    assert str(limit) in too_long.json()["detail"]
    blank = client.post(url, json={"question": "  <>  \n "})  # nothing is left after cleaning
    assert blank.status_code == 400


def test_ask_limit_applies_after_cleaning(client: TestClient, settings: Settings) -> None:
    limit = settings.memory.ask_max_question_chars
    padded = "what changed?" + " " * (limit * 2)  # collapses to a short question
    assert client.post("/v1/vendors/nobody/ask", json={"question": padded}).status_code == 200


def test_ask_writes_its_own_audit_file(client: TestClient, settings: Settings) -> None:
    _run(client, "nimbara-hr", "nimbara-hr.txt")
    assert client.post("/v1/vendors/nimbara-hr/ask", json={"question": "Gaps?"}).status_code == 200
    files = list((settings.paths.state_dir / "ask").glob("ask_*.jsonl"))
    assert len(files) == 1


@pytest.mark.parametrize(
    ("exc", "status", "detail"),
    [
        (ConfigError("our words"), 400, "our words"),
        (BudgetExceededError("INTERNAL"), 429, "the cost budget of this request is used up"),
        (LLMError("INTERNAL sk-1"), 502, "a model provider failed"),
    ],
)
def test_ask_error_mapping(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    status: int,
    detail: str,
) -> None:
    def raiser(*a: Any, **k: Any) -> Any:
        raise exc

    monkeypatch.setattr(vendor_routes, "answer_question", raiser)
    r = client.post("/v1/vendors/v/ask", json={"question": "hello"})
    assert r.status_code == status and r.json() == {"detail": detail}


# ----------------------------------------------------------------------------- key enforcement

ROUTES = [
    ("GET", "/version"),
    ("GET", "/metrics"),
    ("POST", "/v1/assessments"),
    ("GET", "/v1/assessments/run_000000000000"),
    ("GET", "/v1/assessments/run_000000000000/report"),
    ("PATCH", "/v1/assessments/run_000000000000/findings/IAM-02"),
    ("GET", "/v1/vendors"),
    ("GET", "/v1/vendors/nimbara-hr/history"),
    ("POST", "/v1/vendors/nimbara-hr/ask"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_needs_the_key(settings: Settings, method: str, path: str) -> None:
    with TestClient(create_app(settings)) as bare:  # no key header
        r = bare.request(method, path, json={"question": "x"} if method != "GET" else None)
        assert r.status_code == 401
        assert r.json() == {"detail": "invalid or missing API key"}
        wrong = bare.request(method, path, headers={"X-API-Key": "wrong-wrong-wrong-key"})
        assert wrong.status_code == 401


def test_health_is_public(settings: Settings) -> None:
    with TestClient(create_app(settings)) as bare:
        assert bare.get("/health").status_code == 200


def test_the_routes_list_is_complete(client: TestClient) -> None:
    declared = {
        (m.upper(), p)
        for p, ops in client.get("/openapi.json").json()["paths"].items()
        for m in ops
        if p != "/health"
    }
    ids = {"{run_id}": "run_000000000000", "{control_id}": "IAM-02", "{vendor_id}": "nimbara-hr"}
    concrete = set()
    for m, p in declared:
        for k, v in ids.items():
            p = p.replace(k, v)
        concrete.add((m, p))
    assert concrete == set(ROUTES)


# ----------------------------------------------------------------------------- OpenAPI


def test_openapi_lists_every_route_with_a_summary(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    expected = {
        "/v1/assessments": {"post"},
        "/v1/assessments/{run_id}": {"get"},
        "/v1/assessments/{run_id}/report": {"get"},
        "/v1/assessments/{run_id}/findings/{control_id}": {"patch"},
        "/v1/vendors": {"get"},
        "/v1/vendors/{vendor_id}/history": {"get"},
        "/v1/vendors/{vendor_id}/ask": {"post"},
        "/health": {"get"},
        "/version": {"get"},
        "/metrics": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert set(paths[path]) == methods
        for method in methods:
            assert paths[path][method]["summary"]


def test_openapi_documents_the_multipart_upload(client: TestClient) -> None:
    op = client.get("/openapi.json").json()["paths"]["/v1/assessments"]["post"]
    schema = op["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert set(schema["properties"]) == {"vendor_id", "files"}
    assert schema["properties"]["files"]["items"]["format"] == "binary"
    assert set(schema["required"]) == {"vendor_id", "files"}
    assert "202" in op["responses"]


def test_docs_page_is_reachable(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_docs_can_be_switched_off(settings_override: Make) -> None:
    s = settings_override(api={"docs_enabled": False})
    with TestClient(create_app(s), headers=_headers(s)) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404


# ----------------------------------------------------------------------------- lifespan


def test_startup_loads_controls_once(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import vendorguard.api.app as app_module

    calls: list[Path] = []
    real = app_module.load_controls

    def counting(path: Path) -> Any:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(app_module, "load_controls", counting)
    with TestClient(create_app(settings), headers=_headers(settings)) as c:
        assert len(c.app.state.controls.controls) == CONTROLS  # type: ignore[attr-defined]
        c.get("/v1/vendors")
        c.get("/v1/vendors")
    assert len(calls) == 1


def test_shutdown_closes_the_job_registry_and_memory(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[str] = []
    with TestClient(create_app(settings), headers=_headers(settings)) as c:
        jobs = c.app.state.jobs  # type: ignore[attr-defined]
        memory = c.app.state.memory  # type: ignore[attr-defined]
        job_close, mem_close = jobs.close, memory.close

        def close_jobs(wait_s: float = 0.0) -> bool:
            closed.append("jobs")
            return bool(job_close(wait_s))

        def close_memory() -> None:
            closed.append("memory")
            mem_close()

        monkeypatch.setattr(jobs, "close", close_jobs)
        monkeypatch.setattr(memory, "close", close_memory)
    assert closed == ["jobs", "memory"]


def test_closed_registry_refuses_new_work(settings: Settings) -> None:
    with TestClient(create_app(settings), headers=_headers(settings)) as c:
        jobs = c.app.state.jobs  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):  # the executor was shut down
        from vendorguard.api.jobs import Job

        jobs.submit(Job(run_id="x", vendor_id="v", folder=settings.paths.state_dir / "x"))
