"""Sourcetype constants for indexed events.

Event-type classification (formerly frozensets here) is data now:
bin/event_categories.json, loaded through ai_common.categories — new Anthropic
event types are a data-only patch, not a code change.
"""

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
