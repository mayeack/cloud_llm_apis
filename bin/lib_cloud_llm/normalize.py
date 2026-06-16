"""Anthropic API -> provider-neutral ai.* normalization.

Each function returns a flattened dict that mixes normalized ai.* keys with an
`anthropic` object that preserves the raw row for lossless fidelity. Cost
amounts are parsed with Decimal to avoid binary-float rounding.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import PROVIDER


def _get(obj, *path, default=None):
    cur = obj
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _cache_creation(result):
    """Return (5m, 1h) cache-creation tokens, handling nested or flat shapes."""
    cc = result.get("cache_creation")
    if isinstance(cc, dict):
        five = cc.get("ephemeral_5m_input_tokens")
        one = cc.get("ephemeral_1h_input_tokens")
        if five is None:
            five = cc.get("5m") or cc.get("ephemeral_5m")
        if one is None:
            one = cc.get("1h") or cc.get("ephemeral_1h")
        return five, one
    # Flattened fallbacks used by some third-party exporters.
    five = result.get("cache_creation_ephemeral_5m_input_tokens") or result.get(
        "ephemeral_5m_input_tokens"
    )
    one = result.get("cache_creation_ephemeral_1h_input_tokens") or result.get(
        "ephemeral_1h_input_tokens"
    )
    return five, one


def cents_to_usd(amount_cents, currency):
    if currency != "USD" or amount_cents is None or amount_cents == "":
        return None
    try:
        usd = Decimal(str(amount_cents)) / Decimal("100")
    except (InvalidOperation, ValueError):
        return None
    # Keep full precision as a string; Splunk coerces to number for stats.
    return format(usd.normalize(), "f")


def _base(api_family, category):
    return {
        "ai.provider": PROVIDER,
        "ai.api_family": api_family,
        "ai.event.category": category,
    }


def _set(ev, key, value):
    if value is not None and value != "":
        ev[key] = value


def _tokens(ev, result):
    five, one = _cache_creation(result)
    _set(ev, "ai.tokens.input.uncached", result.get("uncached_input_tokens"))
    _set(ev, "ai.tokens.cache_creation.5m", five)
    _set(ev, "ai.tokens.cache_creation.1h", one)
    _set(ev, "ai.tokens.cache_read", result.get("cache_read_input_tokens"))
    _set(ev, "ai.tokens.output", result.get("output_tokens"))
    _set(ev, "ai.tokens.total", result.get("total_tokens"))
    _set(ev, "ai.request.count", result.get("requests"))
    _set(
        ev,
        "ai.server_tool.web_search.requests",
        _get(result, "server_tool_use", "web_search_requests"),
    )


def _dims(ev, result):
    _set(ev, "ai.model", result.get("model"))
    _set(ev, "ai.service_tier", result.get("service_tier"))
    _set(ev, "ai.context_window", result.get("context_window"))
    _set(ev, "ai.inference_geo", result.get("inference_geo"))
    _set(ev, "ai.speed", result.get("speed"))
    _set(ev, "ai.product_surface", result.get("product"))
    _set(ev, "ai.workspace.id", result.get("workspace_id"))
    _set(ev, "ai.api_key.id", result.get("api_key_id"))


def normalize_usage_row(result, bucket, *, api_family, org_id=None, data_refreshed_at=None):
    ev = _base(api_family, "usage")
    _set(ev, "ai.org.id", org_id)
    _set(ev, "ai.bucket.start", _get(bucket, "starting_at"))
    _set(ev, "ai.bucket.end", _get(bucket, "ending_at"))
    _dims(ev, result)
    _tokens(ev, result)
    _set(ev, "ai.analytics.data_refreshed_at", data_refreshed_at)
    ev["anthropic"] = {"bucket": {k: bucket.get(k) for k in ("starting_at", "ending_at")}, "result": result}
    return ev


def normalize_cost_row(result, bucket, *, api_family, org_id=None, data_refreshed_at=None):
    ev = _base(api_family, "cost")
    _set(ev, "ai.org.id", org_id)
    _set(ev, "ai.bucket.start", _get(bucket, "starting_at"))
    _set(ev, "ai.bucket.end", _get(bucket, "ending_at"))
    _dims(ev, result)
    currency = result.get("currency") or "USD"
    _set(ev, "ai.cost.currency", currency)
    _set(ev, "ai.cost.amount_cents", result.get("amount"))
    _set(ev, "ai.cost.list_amount_cents", result.get("list_amount"))
    _set(ev, "ai.cost.amount_usd", cents_to_usd(result.get("amount"), currency))
    _set(ev, "ai.cost.list_amount_usd", cents_to_usd(result.get("list_amount"), currency))
    _set(ev, "ai.cost.type", result.get("cost_type"))
    _set(ev, "ai.cost.token_type", result.get("token_type"))
    _set(ev, "ai.cost.description", result.get("description"))
    _set(ev, "ai.analytics.data_refreshed_at", data_refreshed_at)
    ev["anthropic"] = {"bucket": {k: bucket.get(k) for k in ("starting_at", "ending_at")}, "result": result}
    return ev


def _actor(ev, row, redact_email_fn=None, redact_ip_fn=None):
    actor = row.get("actor") or {}
    _set(ev, "ai.actor.type", actor.get("type"))
    _set(ev, "ai.actor.id", actor.get("user_id"))
    email = actor.get("email") or actor.get("email_address")
    if email and redact_email_fn:
        email = redact_email_fn(email)
    _set(ev, "ai.actor.email", email)
    _set(ev, "ai.actor.name", actor.get("name"))
    if actor.get("deleted") is not None:
        ev["ai.actor.deleted"] = bool(actor.get("deleted"))


def normalize_user_usage_row(row, *, org_id=None, data_refreshed_at=None,
                             redact_email_fn=None):
    ev = _base("enterprise_analytics", "usage")
    _set(ev, "ai.org.id", org_id)
    _actor(ev, row, redact_email_fn=redact_email_fn)
    _dims(ev, row)
    _tokens(ev, row)
    _set(ev, "ai.analytics.data_refreshed_at", data_refreshed_at)
    ev["anthropic"] = {"result": row}
    return ev


def normalize_user_cost_row(row, *, org_id=None, data_refreshed_at=None,
                            redact_email_fn=None):
    ev = _base("enterprise_analytics", "cost")
    _set(ev, "ai.org.id", org_id)
    _actor(ev, row, redact_email_fn=redact_email_fn)
    _dims(ev, row)
    currency = row.get("currency") or "USD"
    _set(ev, "ai.cost.currency", currency)
    _set(ev, "ai.cost.amount_cents", row.get("amount"))
    _set(ev, "ai.cost.list_amount_cents", row.get("list_amount"))
    _set(ev, "ai.cost.amount_usd", cents_to_usd(row.get("amount"), currency))
    _set(ev, "ai.cost.list_amount_usd", cents_to_usd(row.get("list_amount"), currency))
    _set(ev, "ai.cost.type", row.get("cost_type"))
    _set(ev, "ai.cost.token_type", row.get("token_type"))
    _set(ev, "ai.request.count", row.get("requests"))
    _set(ev, "ai.analytics.data_refreshed_at", data_refreshed_at)
    ev["anthropic"] = {"result": row}
    return ev


def normalize_engagement_row(kind, row, *, org_id=None, data_refreshed_at=None,
                             redact_email_fn=None):
    """Normalize a row from /summaries, /users, /projects, /skills, /connectors."""
    ev = _base("enterprise_analytics", "engagement")
    ev["ai.engagement.kind"] = kind
    _set(ev, "ai.org.id", org_id)
    _set(ev, "ai.analytics.data_refreshed_at", data_refreshed_at)
    _set(ev, "ai.event.created_at", row.get("date") or row.get("starting_at"))

    _set(ev, "ai.engagement.daily_active_users", row.get("daily_active_users"))
    _set(ev, "ai.engagement.weekly_active_users", row.get("weekly_active_users"))
    _set(ev, "ai.engagement.monthly_active_users", row.get("monthly_active_users"))
    _set(ev, "ai.engagement.assigned_seats", row.get("assigned_seats"))
    _set(ev, "ai.engagement.pending_invites", row.get("pending_invites"))
    _set(ev, "ai.engagement.conversation.count", row.get("conversation_count") or row.get("conversations"))
    _set(ev, "ai.engagement.message.count", row.get("message_count") or row.get("messages"))

    if kind == "connectors":
        _set(ev, "ai.engagement.connector.name", row.get("name") or row.get("connector"))
        _set(ev, "ai.engagement.connector.distinct_users", row.get("distinct_users"))
    if kind == "skills":
        _set(ev, "ai.governance.object_type", "skill")
        _set(ev, "ai.governance.object_id", row.get("id") or row.get("name"))
    if kind == "projects":
        _set(ev, "ai.governance.object_type", "project")
        _set(ev, "ai.governance.project_id", row.get("id") or row.get("project_id"))
    if kind == "users":
        _actor(ev, {"actor": row}, redact_email_fn=redact_email_fn)

    ev["anthropic"] = {"result": row}
    return ev


# --- compliance (indexed raw, redaction applied in place) -------------------

# Event types that indicate raw user content was retrieved through a compliance
# endpoint, used to set ai.risk.content_retrieved on raw activity events.
CONTENT_RETRIEVAL_HINTS = (
    "compliance_api_accessed",
    "content_retrieved",
    "chat_exported",
    "file_downloaded",
    "messages_retrieved",
)

DELETION_HINTS = ("_deleted", "_delete", "_removed", "_revoked")


def compliance_risk_flags(activity_type):
    t = (activity_type or "").lower()
    content = any(h in t for h in CONTENT_RETRIEVAL_HINTS)
    deletion = any(h in t for h in DELETION_HINTS)
    return content, deletion


def redact_activity(activity, redact_email_fn=None, redact_ip_fn=None):
    """Mutate a raw Activity object to redact actor PII when enabled."""
    actor = activity.get("actor")
    if not isinstance(actor, dict):
        return activity
    if redact_email_fn and actor.get("email_address"):
        actor["email_address"] = redact_email_fn(actor["email_address"])
    if redact_ip_fn and actor.get("ip_address"):
        actor["ip_address"] = redact_ip_fn(actor["ip_address"])
    return activity
