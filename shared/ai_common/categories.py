"""Data-driven event classification: ordered first-match-wins glob rules.

Each provider TA ships a rules file (``bin/event_categories.json``) mapping its
native event-type vocabulary onto the ai.* closed vocabularies, so new provider
event types are a data-only patch — no code change. Rule order is significant
and is contract semantics (docs/ai-schema.md).

File shape::

    {
      "version": 1,
      "vendor": "anthropic",
      "category_rules": [["user_signed_in_*", "authentication"], ...],
      "default_category": "usage",
      "action_rules":    [["user_signed_in_*", "login"], ...],
      "default_action": "unknown",
      "resource_rules":  [["project*", "project"], ...],
      "default_resource": "other",
      "outcome_rules":   [["*_failed", "failure"], ...],
      "default_outcome": "success"
    }
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ai_common import schema


class RuleSet:
    """Ordered glob rules; first match wins, else the default."""

    def __init__(self, rules: Sequence[Sequence[str]], default: Optional[str]):
        self._rules: List[Tuple[str, str]] = [(p, v) for p, v in rules]
        self._default = default

    def match(self, name: Optional[str]) -> Optional[str]:
        if name:
            for pattern, value in self._rules:
                if fnmatchcase(name, pattern):
                    return value
        return self._default


class EventRules:
    """A provider's full classification rule file, validated against the schema."""

    def __init__(self, data: Dict[str, Any]):
        self.version = data["version"]
        self.vendor = data["vendor"]
        self.category = RuleSet(data["category_rules"], data["default_category"])
        self.action = RuleSet(data.get("action_rules", []), data.get("default_action", schema.ACTION_UNKNOWN))
        self.resource = RuleSet(data.get("resource_rules", []), data.get("default_resource", "other"))
        self.outcome = RuleSet(data.get("outcome_rules", []), data.get("default_outcome", schema.OUTCOME_SUCCESS))
        self._validate(data)

    def _validate(self, data: Dict[str, Any]) -> None:
        problems = []
        for _, value in list(data["category_rules"]) + [(None, data["default_category"])]:
            if value not in schema.CATEGORIES:
                problems.append(f"category {value!r}")
        for _, value in list(data.get("action_rules", [])) + [(None, data.get("default_action", schema.ACTION_UNKNOWN))]:
            if value not in schema.ACTIONS:
                problems.append(f"action {value!r}")
        for _, value in list(data.get("resource_rules", [])) + [(None, data.get("default_resource", "other"))]:
            if value not in schema.RESOURCE_TYPES:
                problems.append(f"resource type {value!r}")
        for _, value in list(data.get("outcome_rules", [])) + [(None, data.get("default_outcome", schema.OUTCOME_SUCCESS))]:
            if value not in schema.OUTCOMES:
                problems.append(f"outcome {value!r}")
        if problems:
            raise ValueError("event rules outside ai.* vocabulary: " + ", ".join(problems))

    @classmethod
    def load(cls, path: str) -> "EventRules":
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle))
