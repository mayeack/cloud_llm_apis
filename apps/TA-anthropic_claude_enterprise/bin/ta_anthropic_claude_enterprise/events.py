"""Event normalization for Splunk indexing."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ta_anthropic_claude_enterprise.constants import is_auth_event_type, is_change_event_type

# Top-level Activity keys we remap explicitly; everything else the API sends
# (type-specific detail fields like filename, current_role, visibility, ...)
# passes through under its own name so no audit detail is lost.
_ACTIVITY_MAPPED_KEYS = frozenset({"id", "created_at", "type", "event", "actor"})


def normalize_activity(activity: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten Compliance Activity feed records for Splunk search."""
    actor = activity.get("actor") or {}
    event_type = activity.get("type") or activity.get("event")
    normalized = {
        "activity_id": activity.get("id"),
        "created_at": activity.get("created_at"),
        "event_type": event_type,
        "organization_id": activity.get("organization_id"),
        "organization_uuid": activity.get("organization_uuid"),
        "actor_type": actor.get("type"),
        "actor_user_id": actor.get("user_id"),
        "actor_email": actor.get("email_address") or actor.get("email"),
        "actor_ip_address": actor.get("ip_address"),
        "actor_user_agent": actor.get("user_agent"),
        # actor-union extras (api_actor / admin_api_key_actor /
        # unauthenticated_user_actor / scim_directory_sync_actor)
        "actor_api_key_id": actor.get("api_key_id"),
        "actor_admin_api_key_id": actor.get("admin_api_key_id"),
        "actor_unauthenticated_email": actor.get("unauthenticated_email_address"),
        "actor_workos_event_id": actor.get("workos_event_id"),
        "actor_directory_id": actor.get("directory_id"),
        "actor_idp_connection_type": actor.get("idp_connection_type"),
        "claude_chat_id": activity.get("claude_chat_id"),
        "claude_project_id": activity.get("claude_project_id"),
        "file_id": activity.get("file_id"),
        "is_authentication_event": is_auth_event_type(event_type),
        "is_change_event": is_change_event_type(event_type),
        "vendor": "anthropic",
        "product": "claude_enterprise",
        "source_type_category": "compliance_activity",
    }
    for key, value in activity.items():
        if key not in _ACTIVITY_MAPPED_KEYS and key not in normalized:
            normalized[key] = value
    return normalized


def wrap_directory_record(
    record: Dict[str, Any],
    record_type: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap directory sync records with common metadata."""
    payload = {
        "record_type": record_type,
        "vendor": "anthropic",
        "product": "claude_enterprise",
        "source_type_category": f"compliance_{record_type}",
    }
    payload.update(record)
    if extra:
        payload.update(extra)
    return payload


def wrap_analytics_record(
    record: Dict[str, Any],
    report_type: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap analytics API payloads with report metadata."""
    payload = {
        "report_type": report_type,
        "vendor": "anthropic",
        "product": "claude_enterprise",
        "source_type_category": f"analytics_{report_type}",
    }
    payload.update(record)
    _flatten_actor_fields(payload)
    _normalize_cost_fields(payload, report_type)
    if extra:
        payload.update(extra)
    return payload


def wrap_spend_limit_record(
    record: Dict[str, Any],
    record_type: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize spend limit API rows."""
    payload = {
        "record_type": record_type,
        "vendor": "anthropic",
        "product": "claude_enterprise",
        "source_type_category": f"analytics_{record_type}",
    }
    payload.update(record)
    _flatten_actor_fields(payload)
    _normalize_spend_limit_amounts(payload)
    source = record.get("source") or {}
    if isinstance(source, dict):
        payload["limit_source_type"] = source.get("type")
        payload["limit_source_seat_tier"] = source.get("seat_tier")
        payload["limit_source_rbac_group_id"] = source.get("rbac_group_id")
    if record_type == "spend_limit_request":
        spend_summary = record.get("spend_summary") or {}
        if isinstance(spend_summary, dict):
            payload["request_spend_limit_cents"] = spend_summary.get("amount")
            payload["request_period_spend_cents"] = spend_summary.get("period_to_date_spend")
            _apply_cents_to_usd(payload, "request_spend_limit_cents", "request_spend_limit_usd")
            _apply_cents_to_usd(payload, "request_period_spend_cents", "request_period_spend_usd")
    if extra:
        payload.update(extra)
    return payload


def _flatten_actor_fields(record: Dict[str, Any]) -> None:
    actor = record.get("actor")
    if not isinstance(actor, dict):
        return
    email = actor.get("email") or actor.get("email_address")
    if email and "email" not in record:
        record["email"] = email
    if email and "actor_email" not in record:
        record["actor_email"] = email
    user_id = actor.get("user_id")
    if user_id and "user_id" not in record:
        record["user_id"] = user_id


def _normalize_cost_fields(record: Dict[str, Any], report_type: str) -> None:
    if report_type not in {"user_cost", "cost"}:
        return
    if "total_cost_usd" not in record and record.get("amount") is not None:
        _apply_cents_to_usd(record, "amount", "total_cost_usd")


def _normalize_spend_limit_amounts(record: Dict[str, Any]) -> None:
    _apply_cents_to_usd(record, "amount", "spend_limit_usd")
    _apply_cents_to_usd(record, "period_to_date_spend", "period_spend_usd")
    limit_usd = record.get("spend_limit_usd")
    spend_usd = record.get("period_spend_usd")
    if limit_usd is not None and limit_usd > 0 and spend_usd is not None:
        record["utilization_pct"] = round(100.0 * spend_usd / limit_usd, 1)
    else:
        # API amounts are decimal strings in cents ("0.000000" for a zero
        # limit); a zero-limit seat counts as fully utilized.
        try:
            if float(record.get("amount")) == 0.0:
                record["utilization_pct"] = 100.0
        except (TypeError, ValueError):
            pass


def _apply_cents_to_usd(record: Dict[str, Any], cents_field: str, usd_field: str) -> None:
    raw = record.get(cents_field)
    if raw in (None, ""):
        return
    try:
        record[usd_field] = float(raw) / 100.0
    except (TypeError, ValueError):
        return
