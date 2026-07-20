"""Provider-adapter base: builds ai.* envelopes per docs/ai-schema.md.

Serialization obligations enforced here for every provider:
- ``ai`` is the first event key and ``ai.time`` the first key inside it
  (index-time timestamping and fixture monitors read it positionally);
- null/empty-string keys are omitted recursively — the literal string "null"
  must never reach an index;
- timestamps are ISO 8601 UTC, date-only values normalized to midnight.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ai_common import schema
from ai_common.categories import EventRules

_ENVELOPE_ORDER = (
    "time",
    "schema_version",
    "vendor",
    "product",
    "record",
    "event_category",
    "event_type",
    "event_id",
    "action",
    "outcome",
    "model",
    "actor",
    "org",
    "resource",
    "usage",
    "cost",
    "adoption",
)


def to_iso_utc(value: Optional[str]) -> Optional[str]:
    """Normalize a provider timestamp to ISO 8601 UTC; date-only -> midnight."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 10 and text.count("-") == 2:
        return f"{text}T00:00:00Z"
    return text


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cents_to_usd(raw: Any) -> Optional[float]:
    """Provider decimal-string cents -> USD float; None when unparseable."""
    if raw in (None, ""):
        return None
    try:
        return float(raw) / 100.0
    except (TypeError, ValueError):
        return None


def clean(value: Any) -> Any:
    """Recursively drop None / empty-string keys; lists keep their shape."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = clean(item)
            if item is None or item == "":
                continue
            if isinstance(item, dict) and not item:
                continue
            cleaned[key] = item
        return cleaned
    if isinstance(value, list):
        return [clean(item) for item in value if item is not None]
    return value


class ProviderAdapter:
    """Base adapter: subclass per provider, set vendor/product, load rules."""

    vendor: str = ""
    product: str = ""

    def __init__(self, rules: EventRules, collected_at: Optional[str] = None):
        if rules.vendor != self.vendor:
            raise ValueError(f"rules file is for vendor {rules.vendor!r}, adapter is {self.vendor!r}")
        self.rules = rules
        # Injectable snapshot timestamp so fixtures are deterministic.
        self._collected_at = collected_at

    def collected_at(self) -> str:
        return self._collected_at or now_iso_utc()

    def envelope(self, record: str, time_iso: Optional[str], **fields: Any) -> Dict[str, Any]:
        if record not in schema.RECORDS:
            raise ValueError(f"unknown ai.record {record!r}")
        ai: Dict[str, Any] = {
            "time": to_iso_utc(time_iso) or self.collected_at(),
            "schema_version": schema.SCHEMA_VERSION,
            "vendor": self.vendor,
            "product": self.product,
            "record": record,
            "event_category": fields.pop("event_category", None)
            or schema.RECORD_CATEGORY.get(record),
        }
        ai.update(fields)
        ordered = {key: ai[key] for key in _ENVELOPE_ORDER if key in ai}
        ordered.update({key: value for key, value in ai.items() if key not in ordered})
        return ordered

    def build_event(self, ai: Dict[str, Any], raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        event: Dict[str, Any] = {"ai": clean(ai)}
        raw_clean = clean(raw or {})
        if raw_clean:
            event["raw"] = raw_clean
        return event
