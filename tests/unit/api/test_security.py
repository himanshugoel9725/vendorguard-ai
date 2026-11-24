"""Tests for API security: startup guard, AccessGate (key, lockout, limits, body cap), CORS."""

import asyncio
import hashlib
import logging
import math
import string
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from vendorguard.api import app as app_module
from vendorguard.api import security
from vendorguard.api.app import create_app
from vendorguard.api.security import (
    AccessGate,
    RateLimiter,
    check_startup,
    client_key,
    max_body_bytes,
)
from vendorguard.api.uploads import read_form
from vendorguard.config import Settings
from vendorguard.errors import ConfigError

Make = Callable[..., Settings]
PROTECTED = ["/version", "/metrics"]
HARDENING = {"x-content-type-options": "nosniff", "cache-control": "no-store"}


def key_of(s: Settings) -> str:
    return s.api.auth_key.get_secret_value()


def limiter_for(s: Settings) -> RateLimiter:
    return RateLimiter(s.api.rate_limit_per_minute, s.api.rate_limit_max_principals)


# --- direct ASGI harness ---------------------------------------------------------------------


@dataclass
class Result:
    status: int
    headers: dict[str, str]
    body: bytes
    receive_calls: int
    reached: int
    principal: Any = None
    read_bytes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class Recorder:
    """An ASGI app that records that it ran and (optionally) reads the whole body."""

    def __init__(self, read_body: bool = False) -> None:
        self.read_body = read_body
        self.reached = 0
        self.principal: Any = None
        self.read_bytes = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            self.reached += 1
            return
        self.reached += 1
        self.principal = scope.get("state", {}).get("principal")
        if self.read_body:
            while True:
                m = await receive()
                if m["type"] != "http.request":
                    break
                self.read_bytes += len(m.get("body", b""))
                if not m.get("more_body", False):
                    break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def call(
    gate: Any,
    app: Recorder,
    *,
    method: str = "GET",
    path: str = "/version",
    headers: Sequence[tuple[bytes, bytes]] = (),
    client: tuple[str, int] | None = ("203.0.113.5", 4444),
    chunks: Sequence[bytes] = (b"",),
) -> Result:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "http_version": "1.1",
        "headers": list(headers),
        "client": client,
        "server": ("testserver", 80),
    }
    calls = 0
    queue = list(chunks)

    async def receive() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if queue:
            body = queue.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(queue)}
        return {"type": "http.disconnect"}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(gate(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    hdrs = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return Result(start["status"], hdrs, body, calls, app.reached, app.principal, app.read_bytes)


def keyhdr(value: str) -> list[tuple[bytes, bytes]]:
    return [(b"x-api-key", value.encode("utf-8"))]


def gate_for(s: Settings, read_body: bool = False) -> tuple[AccessGate, Recorder]:
    app = Recorder(read_body)
    return AccessGate(app, s, limiter_for(s)), app


# --- startup guard ---------------------------------------------------------------------------


def test_empty_key_refuses_to_start_and_names_the_variable(settings_override: Make) -> None:
    s = settings_override(api={"auth_key": ""})
    with pytest.raises(ConfigError, match="VG_API__AUTH_KEY"):
        check_startup(s)
    with pytest.raises(ConfigError):
        create_app(s)


def test_short_key_refuses_to_start_without_echoing_it(settings_override: Make) -> None:
    s = settings_override()
    short = "k" * (s.api.auth_key_min_chars - 1)
    with pytest.raises(ConfigError) as exc:
        check_startup(settings_override(api={"auth_key": short}))
    assert short not in str(exc.value) and str(s.api.auth_key_min_chars) in str(exc.value)


def _key_with_distinct(s: Settings, distinct: int) -> str:
    n = s.api.auth_key_min_chars
    pool = (string.ascii_letters + string.digits)[:distinct]
    length = max(n, distinct)
    return (pool * math.ceil(length / distinct))[:length]


def test_key_at_both_minimums_is_accepted(settings_override: Make) -> None:
    s = settings_override()
    key = _key_with_distinct(s, s.api.auth_key_min_distinct_chars)
    assert len(key) >= s.api.auth_key_min_chars
    assert len(set(key)) == s.api.auth_key_min_distinct_chars
    check_startup(settings_override(api={"auth_key": key}))


def test_key_one_distinct_char_short_is_refused_without_echo(settings_override: Make) -> None:
    s = settings_override()
    key = _key_with_distinct(s, s.api.auth_key_min_distinct_chars - 1)
    with pytest.raises(ConfigError) as exc:
        check_startup(settings_override(api={"auth_key": key}))
    assert key not in str(exc.value) and "different characters" in str(exc.value)


def test_identical_characters_are_refused(settings_override: Make) -> None:
    s = settings_override()
    key = "a" * s.api.auth_key_min_chars
    with pytest.raises(ConfigError) as exc:
        check_startup(settings_override(api={"auth_key": key}))
    assert key not in str(exc.value)


def test_changeme_style_key_follows_the_real_distinct_rule(settings_override: Make) -> None:
    s = settings_override()
    key = "changeme-changeme"
    assert len(key) >= s.api.auth_key_min_chars
    candidate = settings_override(api={"auth_key": key})
    if len(set(key)) >= s.api.auth_key_min_distinct_chars:
        check_startup(candidate)  # passes the distinct rule: only a weaker check would refuse
    else:
        with pytest.raises(ConfigError):
            check_startup(candidate)


@pytest.mark.parametrize("pad", [" {k}", "{k} ", " {k} ", "{k}\n", "\t{k}"])
def test_key_with_surrounding_whitespace_is_refused(settings_override: Make, pad: str) -> None:
    s = settings_override()
    key = pad.format(k=key_of(s))
    assert len(key) >= s.api.auth_key_min_chars
    with pytest.raises(ConfigError) as exc:
        check_startup(settings_override(api={"auth_key": key}))
    assert key_of(s) not in str(exc.value)


def test_auth_off_is_allowed_on_loopback_only(settings_override: Make) -> None:
    for host in ("127.0.0.1", "::1", "localhost"):
        check_startup(settings_override(api={"auth_enabled": False, "auth_key": "", "host": host}))
    for host in ("0.0.0.0", "192.168.1.5", "example.com", "::"):  # noqa: S104
        bad = settings_override(api={"auth_enabled": False, "auth_key": "", "host": host})
        with pytest.raises(ConfigError, match="api.auth_enabled"):
            check_startup(bad)
        with pytest.raises(ConfigError):
            create_app(bad)


def test_auth_on_may_listen_on_the_network(settings_override: Make) -> None:
    check_startup(settings_override(api={"host": "0.0.0.0"}))  # noqa: S104


@pytest.mark.parametrize("origin", ["*", "null", " NULL ", " * "])
def test_wildcard_cors_origins_are_rejected_by_settings(
    settings_override: Make, origin: str
) -> None:
    with pytest.raises(Exception, match="cors_origins"):
        settings_override(api={"cors_origins": ["http://localhost:5173", origin]})


def test_main_turns_config_error_into_system_exit(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override(api={"auth_key": ""})
    monkeypatch.setattr(app_module, "get_settings", lambda: s)
    with pytest.raises(SystemExit) as exc:
        app_module.main()
    assert str(exc.value).startswith("error: ") and "VG_API__AUTH_KEY" in str(exc.value)


@pytest.mark.parametrize("trust", [False, True])
def test_main_passes_proxy_headers_setting_to_uvicorn(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch, trust: bool
) -> None:
    s = settings_override(api={"trust_proxy_headers": trust})
    captured: dict[str, Any] = {}
    monkeypatch.setattr(app_module, "get_settings", lambda: s)
    monkeypatch.setattr(app_module.uvicorn, "run", lambda app, **kw: captured.update(kw))
    app_module.main()
    assert captured["proxy_headers"] is trust
    assert captured["host"] == s.api.host and captured["port"] == s.api.port


# --- H1: the gate runs before any body is read -----------------------------------------------


def test_bad_key_with_large_body_is_401_and_receive_is_never_called(
    settings_override: Make,
) -> None:
    s = settings_override()
    gate, app = gate_for(s, read_body=True)
    big = [b"x" * 100_000] * 5
    r = call(gate, app, method="POST", path="/v1/assessments", headers=keyhdr("nope"), chunks=big)
    assert r.status == 401 and r.receive_calls == 0 and app.reached == 0
    assert r.body == b'{"detail": "invalid or missing API key"}'


def test_missing_key_with_body_never_touches_receive(settings_override: Make) -> None:
    gate, app = gate_for(settings_override(), read_body=True)
    r = call(gate, app, method="POST", chunks=[b"abc"])
    assert r.status == 401 and r.receive_calls == 0 and app.reached == 0


def test_authorised_request_reaches_the_app_and_sets_the_principal(
    settings_override: Make,
) -> None:
    s = settings_override()
    gate, app = gate_for(s, read_body=True)
    r = call(gate, app, method="POST", headers=keyhdr(key_of(s)), chunks=[b"abc"])
    assert r.status == 200 and app.reached == 1 and r.principal == "key"
    assert r.receive_calls >= 1 and r.read_bytes == 3


def test_rate_limited_request_never_reads_the_body(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 1})
    gate, app = gate_for(s, read_body=True)
    assert call(gate, app, headers=keyhdr(key_of(s))).status == 200
    r = call(gate, app, headers=keyhdr(key_of(s)), chunks=[b"x" * 10])
    assert r.status == 429 and r.receive_calls == 0 and app.reached == 1


def test_non_http_scopes_pass_straight_through(settings_override: Make) -> None:
    gate, app = gate_for(settings_override())

    async def noop(*_: Any) -> None:
        return None

    asyncio.run(gate({"type": "lifespan"}, noop, noop))
    assert app.reached == 1


# --- key check -------------------------------------------------------------------------------


@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("key", [None, "wrong-key-0123456789abcdef", "", "schlüssel-✓-ключ"])
def test_bad_keys_get_the_same_401(settings_override: Make, path: str, key: str | None) -> None:
    s = settings_override()
    gate, app = gate_for(s)
    r = call(gate, app, path=path, headers=keyhdr(key) if key is not None else [])
    assert r.status == 401 and app.reached == 0
    assert r.body == b'{"detail": "invalid or missing API key"}'


def test_401_body_is_identical_for_every_failure(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 100})
    bodies = set()
    for key in (None, "x", key_of(s) + "x", key_of(s)[:-1], "ключ"):
        gate, app = gate_for(s)
        r = call(gate, app, headers=keyhdr(key) if key is not None else [])
        bodies.add((r.status, r.body))
    assert len(bodies) == 1


def test_duplicate_key_headers_are_401_even_if_both_are_right(settings_override: Make) -> None:
    s = settings_override()
    gate, app = gate_for(s)
    two = keyhdr(key_of(s)) * 2
    assert call(gate, app, headers=two).status == 401
    mixed = keyhdr(key_of(s)) + keyhdr("other")
    assert call(gate, app, headers=mixed).status == 401
    assert app.reached == 0


@pytest.mark.parametrize("path", PROTECTED)
def test_correct_key_is_accepted(settings_override: Make, path: str) -> None:
    s = settings_override()
    gate, app = gate_for(s)
    assert call(gate, app, path=path, headers=keyhdr(key_of(s))).status == 200


def test_health_needs_no_key_and_is_not_limited(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 1})
    gate, app = gate_for(s)
    codes = [call(gate, app, path="/health").status for _ in range(5)]
    assert codes == [200] * 5 and app.reached == 5


def test_compare_digest_gets_sha256_digests(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = security.secrets.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(security.secrets, "compare_digest", spy)
    s = settings_override()
    gate, app = gate_for(s)
    assert call(gate, app, headers=keyhdr("wrong-key")).status == 401
    sha = lambda v: hashlib.sha256(v.encode()).digest()  # noqa: E731
    assert calls == [(sha("wrong-key"), sha(key_of(s)))]


def test_key_is_never_echoed_or_logged(
    settings_override: Make, caplog: pytest.LogCaptureFixture
) -> None:
    s = settings_override()
    wrong = "wrong-key-secret-0123456789"
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(s), headers={"X-API-Key": wrong}) as c:
        bad = c.get("/version")
    with TestClient(create_app(s), headers={"X-API-Key": key_of(s)}) as c:
        good = [c.get(p) for p in ("/version", "/metrics", "/health")]
    for r in [bad, *good]:
        assert wrong not in r.text and key_of(s) not in r.text
        assert all(key_of(s) not in v and wrong not in v for v in r.headers.values())
    assert key_of(s) not in caplog.text and wrong not in caplog.text


# --- fail lockout ----------------------------------------------------------------------------


def test_lockout_blocks_even_the_correct_key_until_the_window_passes(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(security, "monotonic_s", lambda: now[0])
    s = settings_override()
    limit = s.api.rate_limit_per_minute
    gate, app = gate_for(s)
    wrong = keyhdr("wrong-key")
    codes = [call(gate, app, headers=wrong).status for _ in range(limit + 2)]
    assert codes == [401] * limit + [429, 429]
    locked = call(gate, app, headers=keyhdr(key_of(s)))
    assert locked.status == 429 and int(locked.headers["retry-after"]) >= 1
    assert app.reached == 0
    other = call(gate, app, headers=keyhdr(key_of(s)), client=("198.51.100.9", 1))
    assert other.status == 200  # a different client address is unaffected
    now[0] += security.WINDOW_S
    assert call(gate, app, headers=keyhdr(key_of(s))).status == 200


def test_failed_attempts_do_not_use_up_the_key_bucket(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 3})
    gate, app = gate_for(s)
    for _ in range(2):
        call(gate, app, headers=keyhdr("wrong"))
    codes = [
        call(gate, app, headers=keyhdr(key_of(s)), client=("198.51.100.1", 1)).status
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


def test_ipv6_clients_in_one_slash_64_share_the_lockout(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 2})
    gate, app = gate_for(s)
    a = ("2001:db8:1:2::1", 1)
    b = ("2001:db8:1:2:dead:beef:0:7", 1)
    c = ("2001:db8:1:3::1", 1)
    assert [call(gate, app, headers=keyhdr("x"), client=a).status for _ in range(2)] == [401, 401]
    assert call(gate, app, headers=keyhdr(key_of(s)), client=b).status == 429
    assert call(gate, app, headers=keyhdr(key_of(s)), client=c).status == 200


def test_request_without_a_client_address_still_works(settings_override: Make) -> None:
    s = settings_override()
    gate, app = gate_for(s)
    r = call(gate, app, headers=keyhdr(key_of(s)), client=None)
    assert r.status == 200
    s_off = settings_override(api={"auth_enabled": False, "auth_key": ""})
    gate2, app2 = gate_for(s_off)
    assert call(gate2, app2, client=None).principal == "ip:unknown"


# --- rate limit and principals ---------------------------------------------------------------


def test_fourth_request_is_429_with_retry_after(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 3})
    with TestClient(create_app(s), headers={"X-API-Key": key_of(s)}) as c:
        assert [c.get("/version").status_code for _ in range(3)] == [200, 200, 200]
        r = c.get("/version")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_window_slides(settings_override: Make, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(security, "monotonic_s", lambda: now[0])
    s = settings_override(api={"rate_limit_per_minute": 2})
    gate, app = gate_for(s)
    h = keyhdr(key_of(s))
    assert [call(gate, app, headers=h).status for _ in range(3)] == [200, 200, 429]
    now[0] += security.WINDOW_S - 1
    assert call(gate, app, headers=h).status == 429
    now[0] += 1
    assert call(gate, app, headers=h).status == 200


def test_auth_disabled_limits_per_client_ip(settings_override: Make) -> None:
    s = settings_override(api={"auth_enabled": False, "auth_key": "", "rate_limit_per_minute": 2})
    gate, app = gate_for(s)
    codes = [call(gate, app).status for _ in range(3)]
    assert codes == [200, 200, 429]
    assert call(gate, app, client=("198.51.100.77", 1)).principal == "ip:198.51.100.77"


def test_forged_x_forwarded_for_does_not_change_the_principal(settings_override: Make) -> None:
    s = settings_override(api={"auth_enabled": False, "auth_key": ""})
    gate, app = gate_for(s)
    plain = call(gate, app).principal
    forged = call(gate, app, headers=[(b"x-forwarded-for", b"6.6.6.6")]).principal
    forged2 = call(gate, app, headers=[(b"x-forwarded-for", b"7.7.7.7, 8.8.8.8")]).principal
    assert plain == forged == forged2 == "ip:203.0.113.5"


def test_forged_x_forwarded_for_shares_the_bucket_through_testclient(
    settings_override: Make,
) -> None:
    s = settings_override(api={"auth_enabled": False, "auth_key": "", "rate_limit_per_minute": 2})
    app = create_app(s)
    with TestClient(app) as c:
        codes = [
            c.get("/version", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
            for i in range(3)
        ]
        assert codes == [200, 200, 429]
        assert app.state.limiter.blocked("ip:testclient") is not None


def test_forged_xff_cannot_dodge_the_failure_lockout(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 2})
    gate, app = gate_for(s)
    for i in range(2):
        call(gate, app, headers=keyhdr("bad") + [(b"x-forwarded-for", f"1.1.1.{i}".encode())])
    r = call(gate, app, headers=keyhdr(key_of(s)) + [(b"x-forwarded-for", b"9.9.9.9")])
    assert r.status == 429


# --- limiter unit tests ----------------------------------------------------------------------


def test_limiter_retry_after_and_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr(security, "monotonic_s", lambda: now[0])
    lim = RateLimiter(1, 10)
    assert lim.hit("a") is None
    retry = lim.hit("a")
    assert retry is not None and retry >= 1
    assert lim.hit("b") is None
    now[0] = 59.9999
    again = lim.hit("a")
    assert again is not None and again >= 1
    now[0] = security.WINDOW_S
    assert lim.hit("a") is None


def test_limiter_is_thread_safe() -> None:
    lim = RateLimiter(50, 10)
    results: list[int | None] = []
    lock = threading.Lock()

    def work() -> None:
        for _ in range(20):
            r = lim.hit("p")
            with lock:
                results.append(r)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r is None for r in results) == 50 and len(results) == 160


def test_limiter_memory_is_bounded(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_max_principals": 50})
    lim = limiter_for(s)
    cap = s.api.rate_limit_max_principals
    for i in range(cap * 4):
        assert lim.hit(f"p{i}") is None
        assert len(lim._hits) <= cap
    assert len(lim._hits) == cap
    assert f"p{cap * 4 - 1}" in lim._hits and "p0" not in lim._hits


def test_limiter_evicts_the_least_recently_seen() -> None:
    lim = RateLimiter(10, 3)
    for name in ("a", "b", "c"):
        lim.hit(name)
    lim.hit("a")  # a is now the most recent; b the oldest
    lim.hit("d")
    assert set(lim._hits) == {"a", "c", "d"}


def test_blocked_counts_nothing() -> None:
    lim = RateLimiter(1, 10)
    for _ in range(5):
        assert lim.blocked("x") is None
    assert "x" not in lim._hits
    assert lim.hit("x") is None  # still the first counted request
    assert lim.blocked("x") is not None
    assert lim.blocked("x") is not None
    assert len(lim._hits["x"]) == 1


def test_empty_windows_are_removed_after_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr(security, "monotonic_s", lambda: now[0])
    lim = RateLimiter(5, 100)
    lim.hit("a")
    lim.hit("b")
    now[0] = security.WINDOW_S
    assert lim.blocked("a") is None and "a" not in lim._hits
    assert lim.hit("b") is None and len(lim._hits["b"]) == 1


# --- client_key ------------------------------------------------------------------------------


def test_client_key_collapses_ipv6_to_the_slash_64() -> None:
    assert client_key("2001:db8:1:2::1") == client_key("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert client_key("2001:db8:1:2::1") != client_key("2001:db8:1:3::1")
    assert client_key("2001:db8:1:2::1") == "2001:db8:1:2::"


def test_client_key_leaves_ipv4_and_other_strings_alone() -> None:
    assert client_key("203.0.113.5") == "203.0.113.5"
    assert client_key("testclient") == "testclient"
    assert client_key("") == ""


# --- body size cap ---------------------------------------------------------------------------


@pytest.fixture
def small(settings_override: Make) -> Settings:
    return settings_override(
        api={"max_json_body_kb": 1, "max_upload_mb": 1, "max_files_per_request": 1}
    )


def test_max_body_bytes_follows_settings(settings_override: Make) -> None:
    s = settings_override(api={"max_upload_mb": 2, "max_files_per_request": 3})
    assert max_body_bytes(s) == int(2 * 1024 * 1024 * 3 * security.MULTIPART_OVERHEAD)
    assert max_body_bytes(s) > 2 * 3 * 1024 * 1024


@pytest.mark.parametrize("value", ["²", "abc", "-1", "1.5", "", "١٢"])
def test_bad_content_length_is_413_not_500(small: Settings, value: str) -> None:
    gate, app = gate_for(small)
    h = keyhdr(key_of(small)) + [(b"content-length", value.encode("utf-8"))]
    r = call(gate, app, method="POST", path="/x", headers=h)
    assert r.status == 413 and app.reached == 0


def test_declared_json_size_boundary(small: Settings) -> None:
    limit = small.api.max_json_body_kb * 1024
    gate, app = gate_for(small)
    key = keyhdr(key_of(small))
    ok = call(
        gate,
        app,
        method="POST",
        path="/x",
        headers=key + [(b"content-length", str(limit).encode())],
    )
    big = call(
        gate,
        app,
        method="POST",
        path="/x",
        headers=key + [(b"content-length", str(limit + 1).encode())],
    )
    assert ok.status == 200 and big.status == 413 and app.reached == 1


def test_streamed_json_body_over_the_cap_is_413_without_content_length(small: Settings) -> None:
    limit = small.api.max_json_body_kb * 1024
    gate, app = gate_for(small, read_body=True)
    chunks = [b"x" * (limit // 2)] * 3  # chunked: more than the cap in total
    r = call(gate, app, method="POST", path="/x", headers=keyhdr(key_of(small)), chunks=chunks)
    assert r.status == 413 and app.read_bytes <= limit
    exact = call(
        gate,
        app,
        method="POST",
        path="/x",
        headers=keyhdr(key_of(small)),
        chunks=[b"x" * (limit // 2)] * 2,
    )
    assert exact.status == 200


def test_upload_path_has_the_larger_limit_but_only_for_post(small: Settings) -> None:
    json_limit = small.api.max_json_body_kb * 1024
    assert max_body_bytes(small) > json_limit
    gate, app = gate_for(small)
    h = keyhdr(key_of(small)) + [(b"content-length", str(json_limit + 1).encode())]
    assert call(gate, app, method="POST", path="/v1/assessments", headers=h).status == 200
    assert call(gate, app, method="GET", path="/v1/assessments", headers=h).status == 413
    assert call(gate, app, method="POST", path="/v1/other", headers=h).status == 413
    over = keyhdr(key_of(small)) + [(b"content-length", str(max_body_bytes(small) + 1).encode())]
    assert call(gate, app, method="POST", path="/v1/assessments", headers=over).status == 413


def test_chunked_upload_over_the_byte_cap_is_413_before_the_route_finishes(
    small: Settings,
) -> None:
    seen: list[int] = []
    app = FastAPI()
    app.add_middleware(AccessGate, settings=small, limiter=limiter_for(small))

    @app.post("/v1/assessments")
    async def upload(request: Request) -> dict[str, int]:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            seen.append(total)
        return {"total": total}

    cap = max_body_bytes(small)
    piece = 100_000

    def body() -> Any:
        for _ in range(cap // piece + 5):
            yield b"x" * piece

    with TestClient(app, headers={"X-API-Key": key_of(small)}) as c:
        r = c.post("/v1/assessments", content=body())  # no Content-Length: chunked
        assert r.status_code == 413
        assert max(seen, default=0) <= cap  # TestClient may send one message: then none is seen
        ok = c.post("/v1/assessments", content=b"x" * 1000)
        assert ok.status_code == 200 and ok.json() == {"total": 1000}


def test_json_route_over_the_cap_is_413_with_the_real_app(small: Settings) -> None:
    app = create_app(small)
    limit = small.api.max_json_body_kb * 1024
    with TestClient(app, headers={"X-API-Key": key_of(small)}) as c:
        r = c.post("/version", content=b"x" * (limit + 1))
        assert r.status_code == 413
        assert c.post("/version", content=b"x" * limit).status_code == 405  # reached routing


# --- read_form behind the gate ---------------------------------------------------------------


@pytest.fixture
def form_client(settings_override: Make) -> tuple[TestClient, Settings]:
    s = settings_override(api={"max_files_per_request": 2, "max_form_fields": 2})
    app = FastAPI()
    app.add_middleware(AccessGate, settings=s, limiter=limiter_for(s))

    @app.post("/v1/assessments")
    async def form(request: Request) -> dict[str, int]:
        data = await read_form(request, s)
        files = [v for v in data.values() if hasattr(v, "filename")]
        return {"files": len(files), "fields": len(data) - len(files)}

    return TestClient(app, headers={"X-API-Key": key_of(s)}), s


def test_form_within_limits_is_read(form_client: tuple[TestClient, Settings]) -> None:
    c, _ = form_client
    r = c.post(
        "/v1/assessments",
        files=[("f1", ("a.txt", b"x")), ("f2", ("b.txt", b"y"))],
        data={"vendor": "v"},
    )
    assert r.status_code == 200 and r.json() == {"files": 2, "fields": 1}


def test_too_many_files_is_413(form_client: tuple[TestClient, Settings]) -> None:
    c, s = form_client
    files = [(f"f{i}", (f"a{i}.txt", b"x")) for i in range(s.api.max_files_per_request + 1)]
    r = c.post("/v1/assessments", files=files)
    # Starlette turns its own MultiPartException into a 400 inside an app (see the next tests
    # for the 413 mapping in read_form itself): either way the request is refused.
    assert r.status_code in (400, 413) and "too many" in r.json()["detail"].lower()


def test_too_many_fields_is_413(form_client: tuple[TestClient, Settings]) -> None:
    c, s = form_client
    data = {f"k{i}": "v" for i in range(s.api.max_form_fields + 1)}
    r = c.post("/v1/assessments", data=data, files=[("f", ("a.txt", b"x"))])
    assert r.status_code in (400, 413) and "too many" in r.json()["detail"].lower()


def test_broken_multipart_is_400_or_422_never_500(
    form_client: tuple[TestClient, Settings],
) -> None:
    c, _ = form_client
    r = c.post(
        "/v1/assessments",
        content=b"garbage",
        headers={"Content-Type": "multipart/form-data; boundary=zzz"},
    )
    assert r.status_code == 400


# --- headers, CORS, docs, 422 ----------------------------------------------------------------


def test_hardening_headers_on_200_401_413_429(settings_override: Make) -> None:
    s = settings_override(api={"rate_limit_per_minute": 2, "max_json_body_kb": 1})
    gate, app = gate_for(s)
    key = keyhdr(key_of(s))
    results = [
        call(gate, app, path="/health"),  # 200, public
        call(gate, app, headers=keyhdr("bad")),  # 401
        call(gate, app, method="POST", headers=key + [(b"content-length", b"99999")]),  # 413
        call(gate, app, headers=key),  # 200 (uses the single allowed hit)
        call(gate, app, headers=key),  # 429
    ]
    assert [r.status for r in results] == [200, 401, 413, 200, 429]
    for r in results:
        for k, v in HARDENING.items():
            assert r.headers[k] == v


def test_hardening_headers_are_not_duplicated(settings_override: Make) -> None:
    class Own(Recorder):
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"cache-control", b"max-age=5")],
                }
            )
            await send({"type": "http.response.body", "body": b""})

    s = settings_override()
    gate = AccessGate(Own(), s, limiter_for(s))
    r = call(gate, Own(), path="/health")
    assert r.headers["cache-control"] == "max-age=5"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_allowed_origin_gets_cors_header_on_a_gate_401(settings_override: Make) -> None:
    s = settings_override()
    origin = s.api.cors_origins[0]
    with TestClient(create_app(s)) as c:
        r = c.get("/version", headers={"Origin": origin})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == origin
    assert r.headers["x-content-type-options"] == "nosniff"


def test_allowed_origin_gets_cors_header_on_public_path(settings_override: Make) -> None:
    s = settings_override()
    origin = s.api.cors_origins[0]
    with TestClient(create_app(s)) as c:
        r = c.get("/health", headers={"Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in r.headers


def test_disallowed_origin_gets_no_cors_header(settings_override: Make) -> None:
    with TestClient(create_app(settings_override())) as c:
        r = c.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_preflight_allows_only_listed_methods_and_headers(settings_override: Make) -> None:
    s = settings_override()
    origin = s.api.cors_origins[0]
    with TestClient(create_app(s)) as c:
        r = c.options(
            "/version",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key, Content-Type",
            },
        )
        bad = c.options(
            "/version", headers={"Origin": origin, "Access-Control-Request-Method": "DELETE"}
        )
    assert r.status_code == 200
    methods = {m.strip() for m in r.headers["access-control-allow-methods"].split(",")}
    assert methods == {"GET", "POST", "PATCH"}
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "x-api-key" in allowed and "content-type" in allowed
    assert "access-control-allow-credentials" not in r.headers
    assert bad.status_code == 400


def test_empty_cors_origins_means_no_cors_headers(settings_override: Make) -> None:
    s = settings_override(api={"cors_origins": []})
    with TestClient(create_app(s)) as c:
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_are_public_when_enabled(settings_override: Make, path: str) -> None:
    s = settings_override(api={"docs_enabled": True})
    with TestClient(create_app(s)) as c:
        assert c.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_do_not_exist_when_disabled(settings_override: Make, path: str) -> None:
    s = settings_override(api={"docs_enabled": False})
    with TestClient(create_app(s)) as c:
        assert c.get(path, headers={"X-API-Key": key_of(s)}).status_code == 404
        assert c.get(path).status_code == 401  # and they are no longer a free public path


class Typed(BaseModel):
    n: int


def test_422_has_no_input_and_never_echoes_the_value(settings_override: Make) -> None:
    s = settings_override()
    app = create_app(s)

    @app.post("/v1/typed")
    async def typed(body: Typed) -> dict[str, int]:
        return {"n": body.n}

    secret = "super-secret-document-text"
    with TestClient(app, headers={"X-API-Key": key_of(s)}) as c:
        r = c.post("/v1/typed", json={"n": secret})
        ok = c.post("/v1/typed", json={"n": 3})
    assert ok.json() == {"n": 3}
    assert r.status_code == 422 and secret not in r.text
    errors = r.json()["detail"]
    assert errors and all(set(e) == {"loc", "msg", "type"} for e in errors)


class FakeRequest:
    """Stands in for a Request whose scope has no ``app`` (Starlette re-raises the raw error)."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.kwargs: dict[str, Any] = {}

    async def form(self, **kwargs: Any) -> Any:
        from starlette.formparsers import MultiPartException

        self.kwargs = kwargs
        raise MultiPartException(self.message)


def test_read_form_maps_too_many_parts_to_413_and_passes_the_caps(settings_override: Make) -> None:
    from fastapi import HTTPException

    s = settings_override()
    req = FakeRequest("Too many files. Maximum number of files is 1.")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_form(req, s))  # type: ignore[arg-type]
    assert exc.value.status_code == 413 and exc.value.detail == "too many files or fields"
    assert req.kwargs == {
        "max_files": s.api.max_files_per_request,
        "max_fields": s.api.max_form_fields,
    }


def test_read_form_maps_other_form_errors_to_400(settings_override: Make) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_form(FakeRequest("Missing boundary in multipart."), settings_override()))  # type: ignore[arg-type]
    assert exc.value.status_code == 400 and exc.value.detail == "the form is not valid"


def test_chunked_upload_stops_reading_at_the_cap_direct(small: Settings) -> None:
    gate, app = gate_for(small, read_body=True)
    cap = max_body_bytes(small)
    piece = 100_000
    chunks = [b"x" * piece] * (cap // piece + 5)
    r = call(
        gate,
        app,
        method="POST",
        path="/v1/assessments",
        headers=keyhdr(key_of(small)),
        chunks=chunks,
    )
    assert r.status == 413 and app.read_bytes <= cap and r.receive_calls <= len(chunks)
