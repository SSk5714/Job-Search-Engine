"""Polite HTTP for source adapters: identified user agent, per-source rate
limit, bounded retries on 429/5xx honouring Retry-After, strict timeouts.

Tests swap the transport with `set_transport()` so no real request is made."""

import logging
import threading
import time

import httpx

from jobpilot.config import get_settings

log = logging.getLogger("jobpilot.http")
# httpx logs full request URLs at INFO; some sources take their key as a query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)
_transport: httpx.BaseTransport | None = None
_last_call: dict[str, float] = {}
_lock = threading.Lock()
_sleep = time.sleep  # patched in tests


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport
    _last_call.clear()


class SourceHTTPError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class SourceClient:
    def __init__(self, source_code: str, rate_limit_per_min: int = 30, max_retries: int = 2):
        s = get_settings()
        self.source = source_code
        self.min_interval = 60.0 / max(rate_limit_per_min, 1)
        self.max_retries = max_retries
        self.client = httpx.Client(
            transport=_transport,
            timeout=s.http_timeout_s,
            headers={"User-Agent": s.http_user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    def _throttle(self) -> None:
        with _lock:
            wait = _last_call.get(self.source, 0) + self.min_interval - time.monotonic()
            if wait > 0 and _transport is None:
                _sleep(wait)
            _last_call[self.source] = time.monotonic()

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            allow_404: bool = False) -> httpx.Response | None:
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.client.get(url, params=params, headers=headers)
            except httpx.TimeoutException as e:
                if attempt == self.max_retries:
                    raise SourceHTTPError("timeout", f"{self.source}: request timed out") from e
                continue
            except httpx.HTTPError as e:
                if attempt == self.max_retries:
                    raise SourceHTTPError("unreachable", f"{self.source}: {type(e).__name__}") from e
                continue
            if resp.status_code == 404 and allow_404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise SourceHTTPError("rate_limited" if resp.status_code == 429 else "server_error",
                                          f"{self.source}: HTTP {resp.status_code}", resp.status_code)
                retry_after = resp.headers.get("retry-after", "")
                delay = min(float(retry_after), 30.0) if retry_after.isdigit() else 2.0 * (attempt + 1)
                if _transport is None:
                    _sleep(delay)
                continue
            if resp.status_code in (401, 403):
                raise SourceHTTPError("forbidden", f"{self.source}: access refused (HTTP {resp.status_code})",
                                      resp.status_code)
            if resp.status_code >= 400:
                raise SourceHTTPError("http_error", f"{self.source}: HTTP {resp.status_code}", resp.status_code)
            return resp
        raise SourceHTTPError("exhausted", f"{self.source}: retries exhausted")

    def close(self) -> None:
        self.client.close()
