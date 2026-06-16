"""Unit tests for HTTP retry/error handling. Dev-only; exclude from packaging."""

import io
import os
import sys
import unittest
from urllib.error import HTTPError

BIN = os.path.join(os.path.dirname(__file__), "..", "bin")
sys.path.insert(0, BIN)

from lib_cloud_llm import httpclient as hc  # noqa: E402
from lib_cloud_llm.httpclient import (  # noqa: E402
    AuthScopeError,
    CursorResetError,
    HttpClient,
    RateLimitedError,
)


class _Resp:
    def __init__(self, body):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b.encode("utf-8")


class _FakeOpener:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = 0

    def open(self, req, timeout=None, context=None):
        b = self.behaviors[self.calls]
        self.calls += 1
        if isinstance(b, Exception):
            raise b
        return _Resp(b)


def _http_error(code, retry_after=None):
    hdrs = {}
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return HTTPError("https://api.test/x", code, "err", hdrs, io.BytesIO(b"{}"))


def _client(behaviors, **kw):
    c = HttpClient("k", "https://api.test", **kw)
    c._opener = _FakeOpener(behaviors)
    return c


class TestHttpClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_sleep = hc.time.sleep
        hc.time.sleep = lambda *a, **k: None

    @classmethod
    def tearDownClass(cls):
        hc.time.sleep = cls._orig_sleep

    def test_requires_https(self):
        with self.assertRaises(ValueError):
            HttpClient("k", "http://insecure.test")

    def test_403_scope(self):
        c = _client([_http_error(403)])
        with self.assertRaises(AuthScopeError):
            c.get("/x")

    def test_410_cursor_reset(self):
        c = _client([_http_error(410)])
        with self.assertRaises(CursorResetError):
            c.get("/x")

    def test_429_then_success(self):
        c = _client([_http_error(429, retry_after=0), '{"ok":true}'], max_retries=3)
        self.assertEqual(c.get("/x"), {"ok": True})
        self.assertEqual(c._opener.calls, 2)

    def test_5xx_then_success(self):
        c = _client([_http_error(503), '{"data":[]}'], max_retries=3)
        self.assertEqual(c.get("/x"), {"data": []})

    def test_429_exhausted(self):
        c = _client([_http_error(429, 0), _http_error(429, 0)], max_retries=1)
        with self.assertRaises(RateLimitedError):
            c.get("/x")


if __name__ == "__main__":
    unittest.main()
