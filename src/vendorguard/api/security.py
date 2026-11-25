"""API security, as pure ASGI so it runs BEFORE any request body is read or parsed.

``AccessGate`` does, in this order, for every HTTP request except ``/health`` (and the docs when
enabled): the failed-attempt lockout, the ``X-API-Key`` check, the rate limit and the body size
cap (bytes are counted as they arrive, whatever ``Content-Length`` claims). It also adds
hardening headers to every response.
"""

import hashlib
import ipaddress
import json
import secrets
import threading
from collections import OrderedDict, deque
from collections.abc import MutableMapping
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.utils.timeutil import monotonic_s

WINDOW_S = 60.0  # ``api.rate_limit_per_minute`` counts requests per this many seconds
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
PUBLIC_PATHS = frozenset({"/health"})
DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})
UPLOAD_PATHS = frozenset({"/v1/assessments"})  # the only POST that may carry files
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
HARDENING_HEADERS = ((b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store"))
UNAUTHORIZED = "invalid or missing API key"


def check_startup(settings: Settings) -> None:
    """Refuse to start in an unsafe configuration. Raises ConfigError naming the variable and
    never a key value.

    * auth on: the key must exist, have ``api.auth_key_min_chars`` characters, no surrounding
      whitespace and ``api.auth_key_min_distinct_chars`` different characters;
    * auth off: only on a loopback host (an open API must not listen on the network).
    """
    api = settings.api
    if not api.auth_enabled:
        if api.host not in LOOPBACK_HOSTS:
            raise ConfigError(
                f"api.auth_enabled is false but api.host is '{api.host}': an API without a key may "
                "only listen on 127.0.0.1"
            )
        return
    key = api.auth_key.get_secret_value()
    if not key:
        raise ConfigError("the API needs a key: set VG_API__AUTH_KEY in .env (api.auth_enabled)")
    if key != key.strip() or len(key) < api.auth_key_min_chars:
        raise ConfigError(
            f"VG_API__AUTH_KEY is too short or has surrounding spaces: use at least "
            f"{api.auth_key_min_chars} characters"
        )
    if len(set(key)) < api.auth_key_min_distinct_chars:
        raise ConfigError(
            f"VG_API__AUTH_KEY is too repetitive: use at least "
            f"{api.auth_key_min_distinct_chars} different characters (a random token is best)"
        )


def client_key(host: str) -> str:
    """The identity used for limits: the address, with IPv6 collapsed to its /64 network (one
    attacker owns a whole /64, so each address must not be a new bucket)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{host}/64", strict=False).network_address)
    return str(ip)


class RateLimiter:
    """Sliding window per principal, in memory, thread-safe, ONE PROCESS ONLY (N workers would
    allow N times the limit). At most ``max_principals`` principals are tracked: the least
    recently seen are dropped, so memory stays bounded."""

    def __init__(self, per_minute: int, max_principals: int) -> None:
        self._limit = per_minute
        self._max = max_principals
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _retry_after(self, principal: str, now: float) -> int | None:
        window = self._hits.get(principal)
        if window is None:
            return None
        while window and now - window[0] >= WINDOW_S:
            window.popleft()
        if not window:
            del self._hits[principal]
            return None
        if len(window) >= self._limit:
            return max(int(WINDOW_S - (now - window[0])) + 1, 1)
        return None

    def blocked(self, principal: str) -> int | None:
        """Seconds to wait if ``principal`` is over the limit, else ``None``. Counts nothing."""
        with self._lock:
            return self._retry_after(principal, monotonic_s())

    def hit(self, principal: str) -> int | None:
        """Count a request. ``None`` if allowed, else the seconds to wait."""
        now = monotonic_s()
        with self._lock:
            retry = self._retry_after(principal, now)
            if retry is not None:
                return retry
            window = self._hits.setdefault(principal, deque())
            window.append(now)
            self._hits.move_to_end(principal)
            while len(self._hits) > self._max:
                self._hits.popitem(last=False)
            return None


def max_body_bytes(settings: Settings) -> int:
    """The largest upload request body: all allowed files plus form overhead."""
    api = settings.api
    files_bytes = api.max_upload_mb * BYTES_PER_MB * api.max_files_per_request
    return int(files_bytes * api.multipart_overhead)


class BodyTooLarge(Exception):
    """Raised inside the receive channel when the body exceeds its limit."""


class AccessGate:
    """Pure ASGI middleware: authentication, rate limit, body cap, hardening headers."""

    def __init__(self, app: ASGIApp, settings: Settings, limiter: RateLimiter) -> None:
        self.app = app
        self._settings = settings
        self._limiter = limiter
        self._public = PUBLIC_PATHS | (DOCS_PATHS if settings.api.docs_enabled else frozenset())
        self._json_limit = settings.api.max_json_body_kb * BYTES_PER_KB
        self._upload_limit = max_body_bytes(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the checks, then the application."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [h for h in HARDENING_HEADERS if h[0] not in present]
                message = {**message, "headers": headers}
            await send(message)

        denied = self._check_access(scope)
        if denied is not None:
            await self._respond(guarded_send, *denied)
            return
        limit = self._body_limit(scope)
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and (
            not (declared.isascii() and declared.isdecimal()) or int(declared) > limit
        ):
            await self._respond(guarded_send, 413, "request body too large")
            return
        total = 0

        async def counted_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise BodyTooLarge
            return message

        try:
            await self.app(scope, counted_receive, guarded_send)
        except BodyTooLarge:
            if started:
                raise
            await self._respond(guarded_send, 413, "request body too large")

    def _body_limit(self, scope: Scope) -> int:
        upload = scope["method"] == "POST" and scope["path"] in UPLOAD_PATHS
        return self._upload_limit if upload else self._json_limit

    def _check_access(self, scope: Scope) -> tuple[int, str, dict[str, str]] | None:
        """``None`` if the request may go on, else ``(status, detail, headers)``."""
        if scope["path"] in self._public:
            return None
        api = self._settings.api
        peer = scope.get("client")
        client = client_key(peer[0]) if peer else "unknown"
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        if api.auth_enabled:
            lockout = self._limiter.blocked(f"fail:{client}")  # first: a guesser is locked out
            if lockout is not None:
                return 429, "too many requests", {"Retry-After": str(lockout)}
            values = Headers(scope=scope).getlist("x-api-key")
            given = values[0] if len(values) == 1 else ""
            if not _same_key(given, api.auth_key.get_secret_value()):
                retry = self._limiter.hit(f"fail:{client}")
                if retry is not None:
                    return 429, "too many requests", {"Retry-After": str(retry)}
                return 401, UNAUTHORIZED, {}
            principal = "key"
        else:
            principal = f"ip:{client}"
        retry = self._limiter.hit(principal)
        if retry is not None:
            return 429, "too many requests", {"Retry-After": str(retry)}
        state["principal"] = principal
        return None

    @staticmethod
    async def _respond(
        send: Any, status: int, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        raw = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        await send({"type": "http.response.start", "status": status, "headers": raw})
        await send({"type": "http.response.body", "body": body})


def _same_key(given: str, expected: str) -> bool:
    """Constant-time comparison of equal-length digests (hides the key length too)."""
    a = hashlib.sha256(given.encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(a, b)


__all__ = [
    "AccessGate",
    "BodyTooLarge",
    "RateLimiter",
    "check_startup",
    "client_key",
    "max_body_bytes",
]
