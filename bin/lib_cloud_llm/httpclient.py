"""HTTPS-only HTTP client with retry/backoff for the Anthropic APIs.

Uses only the Python standard library so no third-party packages need to be
vendored. Enforces HTTPS, sets a stable User-Agent, honors Retry-After on 429,
applies exponential backoff for 5xx, and raises typed exceptions for the
error classes the inputs must handle distinctly (403 scope, 410 cursor reset).
"""

from __future__ import annotations

import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import USER_AGENT


class ApiError(Exception):
    """Base class for API call failures."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class AuthScopeError(ApiError):
    """Raised on HTTP 403 - the key lacks the required scope."""


class CursorResetError(ApiError):
    """Raised on HTTP 410 - a pagination cursor is no longer valid."""


class RateLimitedError(ApiError):
    """Raised when 429 retries are exhausted."""


class HttpClient:
    def __init__(
        self,
        api_key,
        base_url,
        extra_headers=None,
        timeout=30,
        verify_ssl=True,
        proxy=None,
        max_retries=5,
        backoff_base=1.0,
        backoff_cap=60.0,
        logger=None,
    ):
        if not base_url.lower().startswith("https://"):
            # Defense in depth: never transmit credentials over plaintext.
            raise ValueError("base_url must use HTTPS")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)
        self.backoff_cap = float(backoff_cap)
        self.logger = logger

        self._headers = {
            "x-api-key": api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if extra_headers:
            self._headers.update(extra_headers)

        if verify_ssl:
            self._ssl_ctx = ssl.create_default_context()
        else:
            self._ssl_ctx = ssl._create_unverified_context()

        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
        else:
            # Disable implicit environment proxies for predictable behavior.
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    def _log(self, level, msg):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(msg)

    def get(self, path_or_url, params=None):
        """Perform a GET and return the decoded JSON body.

        `path_or_url` may be an absolute https URL (used for cursor
        continuation links) or a path relative to base_url.
        """
        if path_or_url.lower().startswith("https://"):
            url = path_or_url
        elif path_or_url.lower().startswith("http://"):
            raise ValueError("refusing to call a non-HTTPS URL")
        else:
            url = self.base_url + "/" + path_or_url.lstrip("/")

        if params:
            # doseq=True expands list values into repeated key params, e.g.
            # activity_types[]=a&activity_types[]=b
            query = urllib.parse.urlencode(params, doseq=True)
            url = url + ("&" if "?" in url else "?") + query

        attempt = 0
        while True:
            attempt += 1
            try:
                req = urllib.request.Request(url, headers=self._headers, method="GET")
                with self._opener.open(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                body = _safe_read(exc)
                status = exc.code
                if status == 403:
                    raise AuthScopeError(
                        "403 Forbidden: API key lacks required scope", status, body
                    )
                if status == 410:
                    raise CursorResetError(
                        "410 Gone: pagination cursor expired, reset required", status, body
                    )
                if status == 429:
                    if attempt > self.max_retries:
                        raise RateLimitedError("429 retries exhausted", status, body)
                    delay = _retry_after(exc) or self._backoff(attempt)
                    self._log("warning", "429 rate limited; sleeping %.1fs (attempt %d)" % (delay, attempt))
                    time.sleep(delay)
                    continue
                if 500 <= status < 600:
                    if attempt > self.max_retries:
                        raise ApiError("5xx retries exhausted", status, body)
                    delay = self._backoff(attempt)
                    self._log("warning", "%d server error; sleeping %.1fs (attempt %d)" % (status, delay, attempt))
                    time.sleep(delay)
                    continue
                raise ApiError("HTTP %d error" % status, status, body)
            except urllib.error.URLError as exc:
                if attempt > self.max_retries:
                    raise ApiError("network error: %s" % exc.reason)
                delay = self._backoff(attempt)
                self._log("warning", "network error %s; sleeping %.1fs (attempt %d)" % (exc.reason, delay, attempt))
                time.sleep(delay)
                continue

    def _backoff(self, attempt):
        # Exponential backoff with full jitter, capped.
        raw = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
        return random.uniform(0, raw)


def _safe_read(exc):
    try:
        return exc.read().decode("utf-8")
    except Exception:
        return ""


def _retry_after(exc):
    val = exc.headers.get("Retry-After") if exc.headers else None
    if not val:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
