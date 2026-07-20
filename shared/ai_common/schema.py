"""Executable twin of docs/ai-schema.md — the ai.* contract, version 1.0.0.

Adapters and conformance tests import these names; the doc and this module must
change together (semver: additive = minor, breaking = major).
"""

from __future__ import annotations

SCHEMA_VERSION = "1.0.0"

VENDOR_ANTHROPIC = "anthropic"
VENDOR_OPENAI = "openai"
VENDOR_GOOGLE = "google"
VENDORS = frozenset({VENDOR_ANTHROPIC, VENDOR_OPENAI, VENDOR_GOOGLE})

# --- ai.event_category ----------------------------------------------------------
CATEGORY_AUTHENTICATION = "authentication"
CATEGORY_ADMIN_CHANGE = "admin_change"
CATEGORY_CONTENT_ACCESS = "content_access"
CATEGORY_USAGE = "usage"
CATEGORY_COST = "cost"
CATEGORY_POLICY = "policy"
CATEGORY_DATA_EXPORT = "data_export"
CATEGORIES = frozenset(
    {
        CATEGORY_AUTHENTICATION,
        CATEGORY_ADMIN_CHANGE,
        CATEGORY_CONTENT_ACCESS,
        CATEGORY_USAGE,
        CATEGORY_COST,
        CATEGORY_POLICY,
        CATEGORY_DATA_EXPORT,
    }
)

# --- ai.record -------------------------------------------------------------------
RECORD_ACTIVITY = "activity"
RECORDS = frozenset(
    {
        RECORD_ACTIVITY,
        "user",
        "organization",
        "group",
        "chat",
        "file",
        "summary",
        "usage",
        "cost",
        "user_usage",
        "user_cost",
        "user_activity",
        "spend_limit",
        "spend_limit_request",
    }
)

# Fixed category per non-activity record kind (activity is rule-classified).
RECORD_CATEGORY = {
    "user": CATEGORY_POLICY,
    "organization": CATEGORY_POLICY,
    "group": CATEGORY_POLICY,
    "chat": CATEGORY_CONTENT_ACCESS,
    "file": CATEGORY_CONTENT_ACCESS,
    "summary": CATEGORY_USAGE,
    "usage": CATEGORY_USAGE,
    "user_usage": CATEGORY_USAGE,
    "user_activity": CATEGORY_USAGE,
    "cost": CATEGORY_COST,
    "user_cost": CATEGORY_COST,
    "spend_limit": CATEGORY_COST,
    "spend_limit_request": CATEGORY_POLICY,
}

# --- ai.action -------------------------------------------------------------------
ACTION_UNKNOWN = "unknown"
ACTIONS = frozenset(
    {
        "login",
        "logout",
        "login_attempt",
        "create",
        "update",
        "delete",
        "read",
        "export",
        "request",
        ACTION_UNKNOWN,
    }
)

# --- ai.outcome ------------------------------------------------------------------
OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOMES = frozenset({OUTCOME_SUCCESS, OUTCOME_FAILURE})

# --- ai.resource.type --------------------------------------------------------------
RESOURCE_TYPES = frozenset(
    {
        "org",
        "project",
        "user",
        "group",
        "identity",
        "api_key",
        "chat",
        "file",
        "memory",
        "integration",
        "other",
    }
)

# Required on every event (100% coverage — the index-time signature).
REQUIRED_ENVELOPE = ("time", "schema_version", "vendor", "product", "record", "event_category")
# Additionally required when record == activity.
REQUIRED_ACTIVITY = ("event_type", "event_id", "action", "outcome")
