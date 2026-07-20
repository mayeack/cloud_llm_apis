"""Anthropic -> ai.* reference adapter (docs/ai-schema.md v1.0.0).

Replaces the flat-field normalization in the former events.py. Every emitted
event is ``{"ai": {...}, "raw": {...}}``: the contract fields under ai.*, all
unconsumed provider-native fields verbatim under raw.*. Activity classification
(category/action/resource/outcome) is data-driven from bin/event_categories.json
so new Anthropic event types are a data-only patch.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ai_common.adapter import ProviderAdapter, cents_to_usd
from ai_common.categories import EventRules

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "event_categories.json"
)

# Activity keys consumed into ai.*; the resource ids (claude_project_id,
# claude_chat_id, file_id) deliberately stay in raw as well — ai.resource.id is
# a *selection* among them, and the unselected ids must not be lost.
_ACTIVITY_CONSUMED = frozenset({"id", "created_at", "type", "event", "actor", "organization_id", "organization_uuid"})
_ACTOR_CONSUMED = frozenset({"email_address", "email", "user_id", "type", "ip_address", "user_agent"})

_RESOURCE_ID_FIELDS = {"project": "claude_project_id", "chat": "claude_chat_id", "file": "file_id"}


def _split_raw(record: Dict[str, Any], consumed: frozenset) -> Dict[str, Any]:
    return {key: value for key, value in record.items() if key not in consumed}


class AnthropicAdapter(ProviderAdapter):
    vendor = "anthropic"
    product = "claude_enterprise"

    @classmethod
    def default(cls, collected_at: Optional[str] = None) -> "AnthropicAdapter":
        return cls(EventRules.load(RULES_PATH), collected_at=collected_at)

    # ------------------------------------------------------------------ activity
    def activity_event(self, activity: Dict[str, Any]) -> Dict[str, Any]:
        actor = activity.get("actor") or {}
        event_type = activity.get("type") or activity.get("event")

        resource_type = self.rules.resource.match(event_type)
        preferred = _RESOURCE_ID_FIELDS.get(resource_type)
        resource_id = (
            (activity.get(preferred) if preferred else None)
            or activity.get("claude_project_id")
            or activity.get("claude_chat_id")
            or activity.get("file_id")
        )
        resource = None
        if resource_id or resource_type != "other":
            resource = {"type": resource_type, "id": resource_id}

        ai = self.envelope(
            "activity",
            activity.get("created_at"),
            event_category=self.rules.category.match(event_type),
            event_type=event_type,
            event_id=activity.get("id"),
            action=self.rules.action.match(event_type),
            outcome=self.rules.outcome.match(event_type),
            actor={
                "email": actor.get("email_address") or actor.get("email"),
                "id": actor.get("user_id"),
                "type": actor.get("type"),
                "ip": actor.get("ip_address"),
                "user_agent": actor.get("user_agent"),
            },
            org={"id": activity.get("organization_id"), "uuid": activity.get("organization_uuid")},
            resource=resource,
        )
        raw = _split_raw(activity, _ACTIVITY_CONSUMED)
        leftover_actor = _split_raw(actor, _ACTOR_CONSUMED)
        if leftover_actor:
            raw["actor"] = leftover_actor
        return self.build_event(ai, raw)

    # ------------------------------------------------- directory/content records
    def directory_event(self, record: Dict[str, Any], record_type: str) -> Dict[str, Any]:
        """user | organization | group | chat | file snapshot records.

        Snapshots are stamped at COLLECTION time (ai.time = observation moment);
        the subject's own created_at/updated_at stay in raw as data.
        """
        consumed: set = set()
        time_iso = None  # envelope falls back to collected_at()

        actor = None
        org = {"uuid": record.get("organization_uuid")}
        if record_type == "user":
            # For directory snapshots actor.* carries the SUBJECT identity.
            actor = {"email": record.get("email"), "id": record.get("id"), "role": record.get("organization_role")}
            consumed |= {"email", "organization_role", "organization_uuid"}
        elif record_type == "organization":
            org = {"uuid": record.get("uuid")}

        resource_id = record.get("uuid") if record_type == "organization" else record.get("id")
        resource_type = "org" if record_type == "organization" else record_type

        ai = self.envelope(
            record_type,
            time_iso,
            actor=actor,
            org=org,
            resource={"type": resource_type, "id": resource_id},
        )
        return self.build_event(ai, _split_raw(record, frozenset(consumed)))

    # --------------------------------------------------------- analytics reports
    def analytics_event(self, record: Dict[str, Any], report_type: str) -> Dict[str, Any]:
        """summary | usage | cost | user_usage | user_cost | user_activity."""
        time_iso = record.get("starting_at") or record.get("date")
        consumed = {"starting_at"} if record.get("starting_at") else {"date"}

        fields: Dict[str, Any] = {"actor": self._report_actor(record, consumed)}

        if report_type in ("usage", "user_usage"):
            fields["usage"] = self._usage_measures(record, consumed)
            model = record.get("model")
            if report_type == "usage" and model and model != "all":
                fields["model"] = model
        elif report_type in ("cost", "user_cost"):
            amount_usd = record.get("total_cost_usd")
            if amount_usd is None:
                amount_usd = cents_to_usd(record.get("amount"))
            fields["cost"] = {"amount_usd": amount_usd, "currency": record.get("currency")}
            consumed |= {"amount", "total_cost_usd", "currency"}
        elif report_type == "summary":
            fields["adoption"] = {
                "daily_active_users": record.get("daily_active_user_count"),
                "weekly_active_users": record.get("weekly_active_user_count"),
                "monthly_active_users": record.get("monthly_active_user_count"),
                "seats": record.get("seat_count"),
                "pending_invites": record.get("pending_invite_count"),
                "daily_rate": record.get("daily_adoption_rate"),
                "weekly_rate": record.get("weekly_adoption_rate"),
                "monthly_rate": record.get("monthly_adoption_rate"),
            }
            consumed |= {
                "daily_active_user_count", "weekly_active_user_count", "monthly_active_user_count",
                "seat_count", "pending_invite_count",
                "daily_adoption_rate", "weekly_adoption_rate", "monthly_adoption_rate",
            }

        ai = self.envelope(report_type, time_iso, **fields)
        return self.build_event(ai, _split_raw(record, frozenset(consumed)))

    # ------------------------------------------------------------- spend limits
    def spend_limit_event(self, record: Dict[str, Any], record_type: str) -> Dict[str, Any]:
        """spend_limit | spend_limit_request."""
        time_iso = record.get("created_at") or record.get("updated_at")
        consumed = {"created_at"} if record.get("created_at") else {"updated_at"}
        cost: Dict[str, Any] = {}

        if record_type == "spend_limit":
            limit_usd = cents_to_usd(record.get("amount"))
            spend_usd = cents_to_usd(record.get("period_to_date_spend"))
            cost = {"limit_usd": limit_usd, "spend_usd": spend_usd}
            if limit_usd is not None and limit_usd > 0 and spend_usd is not None:
                cost["utilization_pct"] = round(100.0 * spend_usd / limit_usd, 1)
            else:
                # Zero-limit seats count as fully utilized (API sends "0.000000").
                try:
                    if float(record.get("amount")) == 0.0:
                        cost["utilization_pct"] = 100.0
                except (TypeError, ValueError):
                    pass
            consumed |= {"amount", "period_to_date_spend"}
        else:
            spend_summary = record.get("spend_summary") or {}
            if isinstance(spend_summary, dict):
                cost = {
                    "requested_limit_usd": cents_to_usd(spend_summary.get("amount")),
                    "spend_usd": cents_to_usd(spend_summary.get("period_to_date_spend")),
                }
                consumed |= {"spend_summary"}

        user_id = record.get("user_id")
        ai = self.envelope(
            record_type,
            time_iso,
            actor=self._report_actor(record, consumed),
            resource={"type": "user", "id": user_id} if user_id else None,
            cost=cost or None,
        )
        return self.build_event(ai, _split_raw(record, frozenset(consumed)))

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _report_actor(record: Dict[str, Any], consumed: set) -> Optional[Dict[str, Any]]:
        actor = record.get("actor") if isinstance(record.get("actor"), dict) else {}
        email = record.get("email") or actor.get("email") or actor.get("email_address")
        user_id = record.get("user_id") or actor.get("user_id")
        if not email and not user_id:
            return None
        consumed |= {"email", "user_id", "actor"}
        return {"email": email, "id": user_id}

    @staticmethod
    def _usage_measures(record: Dict[str, Any], consumed: set) -> Dict[str, Any]:
        components = [
            record.get("uncached_input_tokens"),
            record.get("cache_read_input_tokens"),
            record.get("cache_creation_input_tokens"),
        ]
        present = [c for c in components if isinstance(c, (int, float))]
        input_tokens = sum(present) if present else None
        output_tokens = record.get("output_tokens")
        total = None
        if input_tokens is not None or output_tokens is not None:
            total = (input_tokens or 0) + (output_tokens or 0)
        consumed |= {"output_tokens"}  # cache-split components deliberately stay in raw
        return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}
