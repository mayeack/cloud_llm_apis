"""HTTP client for Anthropic Compliance and Analytics APIs."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ta_anthropic_claude_enterprise import ADDON_NAME, ANTHROPIC_VERSION, API_BASE_URL

logger = logging.getLogger(f"{ADDON_NAME.lower()}_api_client")

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 5
MAX_PAGE_SIZE = 100


class AnthropicAPIError(Exception):
    """Raised when the Anthropic API returns an error response."""

    def __init__(self, status_code: int, message: str, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AnthropicClient:
    """TLS-only HTTP client with retry/backoff for Anthropic enterprise APIs."""

    def __init__(
        self,
        compliance_api_key: Optional[str] = None,
        analytics_api_key: Optional[str] = None,
        proxy_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.compliance_api_key = compliance_api_key
        self.analytics_api_key = analytics_api_key
        self.timeout = timeout
        self._proxy_handler = None
        if proxy_url:
            self._proxy_handler = urllib.request.ProxyHandler(
                {"http": proxy_url, "https": proxy_url}
            )

    def _build_opener(self) -> urllib.request.OpenerDirector:
        if self._proxy_handler:
            return urllib.request.build_opener(self._proxy_handler)
        return urllib.request.build_opener()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        use_bearer: bool = False,
    ) -> Dict[str, Any]:
        if not api_key:
            raise AnthropicAPIError(401, "API key is required for this request")

        query = ""
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                query = "?" + urllib.parse.urlencode(filtered, doseq=True)

        url = f"{API_BASE_URL}{path}{query}"
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "Accept": "application/json",
            "User-Agent": f"{ADDON_NAME}/1.0.0",
        }
        if use_bearer:
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers["x-api-key"] = api_key

        request = urllib.request.Request(url, method=method, headers=headers)
        opener = self._build_opener()
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                    if not body:
                        return {}
                    return json.loads(body)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429 and attempt < MAX_RETRIES - 1:
                    retry_after = exc.headers.get("Retry-After")
                    sleep_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                    logger.warning(
                        "Rate limited (429), retrying in %s seconds (attempt %s/%s)",
                        sleep_seconds,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(sleep_seconds)
                    last_error = exc
                    continue
                message = self._parse_error_message(body) or exc.reason
                raise AnthropicAPIError(exc.code, message, body) from exc
            except urllib.error.URLError as exc:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    last_error = exc
                    continue
                raise AnthropicAPIError(0, f"Network error: {exc.reason}") from exc

        raise AnthropicAPIError(0, f"Request failed after retries: {last_error}")

    @staticmethod
    def _parse_error_message(body: str) -> Optional[str]:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return error.get("message") or error.get("type")
        return None

    def validate_compliance_key(self) -> Tuple[bool, str]:
        """Probe compliance activities endpoint with limit=1."""
        if not self.compliance_api_key:
            return False, "Compliance API key is not configured"
        try:
            self.compliance_get("/v1/compliance/activities", {"limit": 1})
            return True, "Compliance API key validated successfully"
        except AnthropicAPIError as exc:
            if exc.status_code == 403:
                return False, "Compliance key lacks read:compliance_activities scope or Compliance API is not enabled"
            return False, str(exc)

    def validate_analytics_key(self) -> Tuple[bool, str]:
        """Probe analytics summaries with a minimal date range."""
        if not self.analytics_api_key:
            return False, "Analytics API key is not configured"
        try:
            from datetime import date, timedelta

            end = date.today() - timedelta(days=3)
            start = end - timedelta(days=1)
            self.analytics_get(
                "/v1/organizations/analytics/summaries",
                {"starting_date": start.isoformat(), "ending_date": end.isoformat()},
            )
            return True, "Analytics API key validated successfully"
        except AnthropicAPIError as exc:
            if exc.status_code == 403:
                return False, "Analytics key lacks read:analytics scope"
            return False, str(exc)

    def compliance_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params, api_key=self.compliance_api_key)

    def analytics_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request(
            "GET",
            path,
            params=params,
            api_key=self.analytics_api_key,
            use_bearer=True,
        )

    def paginate_compliance(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data_key: str = "data",
        max_items: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Cursor pagination using after_id / has_more."""
        query = dict(params or {})
        query.setdefault("limit", min(MAX_PAGE_SIZE, max_items or MAX_PAGE_SIZE))
        collected = 0

        while True:
            response = self.compliance_get(path, query)
            items = response.get(data_key, [])
            if not isinstance(items, list):
                break

            for item in items:
                yield item
                collected += 1
                if max_items and collected >= max_items:
                    return

            if not response.get("has_more"):
                break

            last_id = response.get("last_id")
            if not last_id and items:
                last_id = items[-1].get("id")
            if not last_id:
                break
            query["after_id"] = last_id

    def paginate_analytics(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data_key: str = "data",
    ) -> Iterator[Dict[str, Any]]:
        """Page through analytics endpoints using next_page cursor."""
        query = dict(params or {})
        while True:
            response = self.analytics_get(path, query)
            items = response.get(data_key, [])
            if isinstance(items, list):
                for item in items:
                    yield item

            next_page = response.get("next_page")
            if not next_page:
                break
            query["page"] = next_page

    def admin_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Admin API GET using the Compliance/Admin key (x-api-key header)."""
        if not self.compliance_api_key:
            raise AnthropicAPIError(401, "Admin API key is required for this request")
        return self._request("GET", path, params=params, api_key=self.compliance_api_key)

    def paginate_admin(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data_key: str = "data",
    ) -> Iterator[Dict[str, Any]]:
        """Page through Admin API endpoints using next_page cursor."""
        query = dict(params or {})
        while True:
            response = self.admin_get(path, query)
            items = response.get(data_key, [])
            if isinstance(items, list):
                for item in items:
                    yield item

            next_page = response.get("next_page")
            if not next_page:
                break
            query["page"] = next_page
