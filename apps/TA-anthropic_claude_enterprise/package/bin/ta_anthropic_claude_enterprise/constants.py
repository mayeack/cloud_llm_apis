"""Sourcetype constants and event-type classification for indexed events."""

SOURCETYPE_COMPLIANCE_ACTIVITY = "anthropic:compliance:activity"
SOURCETYPE_COMPLIANCE_USER = "anthropic:compliance:user"
SOURCETYPE_COMPLIANCE_ORGANIZATION = "anthropic:compliance:organization"
SOURCETYPE_COMPLIANCE_GROUP = "anthropic:compliance:group"
SOURCETYPE_COMPLIANCE_CHAT_CONTENT = "anthropic:compliance:chat_content"
SOURCETYPE_COMPLIANCE_FILE_METADATA = "anthropic:compliance:file_metadata"
SOURCETYPE_ANALYTICS_SUMMARY = "anthropic:analytics:summary"
SOURCETYPE_ANALYTICS_USAGE = "anthropic:analytics:usage"
SOURCETYPE_ANALYTICS_COST = "anthropic:analytics:cost"
SOURCETYPE_ANALYTICS_USER_USAGE = "anthropic:analytics:user_usage"
SOURCETYPE_ANALYTICS_USER_COST = "anthropic:analytics:user_cost"
SOURCETYPE_ANALYTICS_USER_ACTIVITY = "anthropic:analytics:user_activity"
SOURCETYPE_ANALYTICS_SPEND_LIMIT = "anthropic:analytics:spend_limit"
SOURCETYPE_ANALYTICS_SPEND_LIMIT_REQUEST = "anthropic:analytics:spend_limit_request"

# Authentication events: sign-in/out plus pre-auth SSO attempts. Content events
# (chat/conversation creation) are NOT authentication.
AUTH_EVENT_TYPES = frozenset(
    {
        "user_signed_in_sso",
        "user_signed_in_google",
        "user_signed_in_apple",
        "user_signed_out",
        "user_signed_in_magic_link",
        "user_signed_in_phone_code",
        "sso_login_initiated",
    }
)

# Change classification mirrors the anthropic_claude_change_events eventtype:
# configuration/administrative families minus read-only verbs. The Activity
# Feed has hundreds of types, so classify by family rather than exact names.
CHANGE_EVENT_PREFIXES = (
    "org_",
    "project_",
    "rbac_",
    "group_",
    "platform_memory_",
    "mcp_",
    "integration_",
    "extension_",
    "billing_",
)
_CHANGE_EXACT = frozenset({"conversation_renamed", "conversation_deleted", "user_name_changed"})
_READONLY_SUFFIXES = ("_viewed", "_accessed", "_listed")


def is_auth_event_type(event_type) -> bool:
    return event_type in AUTH_EVENT_TYPES


def is_change_event_type(event_type) -> bool:
    if not event_type or event_type.endswith(_READONLY_SUFFIXES):
        return False
    if event_type in _CHANGE_EXACT:
        return True
    if "api_key_" in event_type or event_type.endswith("_role_updated"):
        return True
    if event_type.startswith("claude_code_") and event_type.endswith("_updated"):
        return True
    return event_type.startswith(CHANGE_EVENT_PREFIXES)
