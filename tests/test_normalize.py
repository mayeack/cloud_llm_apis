"""Unit tests for the ai.* normalizer. Dev-only; exclude from packaging."""

import os
import sys
import unittest

BIN = os.path.join(os.path.dirname(__file__), "..", "bin")
sys.path.insert(0, BIN)

from lib_cloud_llm import normalize  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_usage_nested_cache_creation(self):
        result = {
            "model": "claude-haiku-4-5-20251001",
            "uncached_input_tokens": 1499,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 120,
                "ephemeral_1h_input_tokens": 40,
            },
            "cache_read_input_tokens": 10,
            "output_tokens": 83,
            "requests": 7,
        }
        bucket = {"starting_at": "2026-03-01T00:00:00Z", "ending_at": "2026-03-02T00:00:00Z"}
        ev = normalize.normalize_usage_row(result, bucket, api_family="admin_usage")
        self.assertEqual(ev["ai.tokens.cache_creation.5m"], 120)
        self.assertEqual(ev["ai.tokens.cache_creation.1h"], 40)
        self.assertEqual(ev["ai.tokens.input.uncached"], 1499)
        self.assertEqual(ev["ai.bucket.start"], "2026-03-01T00:00:00Z")
        self.assertEqual(ev["ai.provider"], "anthropic")
        self.assertEqual(ev["ai.event.category"], "usage")

    def test_usage_flat_cache_creation_fallback(self):
        result = {
            "uncached_input_tokens": 10,
            "cache_creation_ephemeral_5m_input_tokens": 5,
            "cache_creation_ephemeral_1h_input_tokens": 3,
        }
        ev = normalize.normalize_usage_row(result, {}, api_family="admin_usage")
        self.assertEqual(ev["ai.tokens.cache_creation.5m"], 5)
        self.assertEqual(ev["ai.tokens.cache_creation.1h"], 3)

    def test_cents_to_usd_decimal(self):
        self.assertEqual(normalize.cents_to_usd("41280.000000", "USD"), "412.8")
        self.assertEqual(normalize.cents_to_usd("1", "USD"), "0.01")
        self.assertEqual(normalize.cents_to_usd("50", "USD"), "0.5")
        self.assertIsNone(normalize.cents_to_usd("100", "EUR"))
        self.assertIsNone(normalize.cents_to_usd(None, "USD"))

    def test_cost_row_usd(self):
        result = {
            "model": "claude-sonnet-4-6",
            "currency": "USD",
            "amount": "41280.000000",
            "list_amount": "50000.000000",
            "cost_type": "tokens",
            "token_type": "output_tokens",
        }
        bucket = {"starting_at": "2026-03-01T00:00:00Z", "ending_at": "2026-03-02T00:00:00Z"}
        ev = normalize.normalize_cost_row(result, bucket, api_family="admin_usage")
        self.assertEqual(ev["ai.cost.amount_usd"], "412.8")
        self.assertEqual(ev["ai.cost.list_amount_usd"], "500")
        self.assertEqual(ev["ai.cost.token_type"], "output_tokens")
        self.assertEqual(ev["ai.event.category"], "cost")

    def test_user_usage_redaction(self):
        row = {
            "actor": {"type": "user_actor", "user_id": "u1", "email": "jane@example.com"},
            "model": "claude-opus-4-1",
            "output_tokens": 5,
        }
        ev = normalize.normalize_user_usage_row(row, redact_email_fn=lambda e: "X@example.com")
        self.assertEqual(ev["ai.actor.email"], "X@example.com")
        self.assertEqual(ev["ai.actor.id"], "u1")

    def test_compliance_risk_flags(self):
        content, deletion = normalize.compliance_risk_flags("compliance_api_accessed")
        self.assertTrue(content)
        self.assertFalse(deletion)
        content, deletion = normalize.compliance_risk_flags("claude_chat_deleted")
        self.assertTrue(deletion)
        content, deletion = normalize.compliance_risk_flags("user_logged_in")
        self.assertFalse(content)
        self.assertFalse(deletion)

    def test_engagement_summary(self):
        row = {"date": "2026-06-01", "daily_active_users": 50, "assigned_seats": 200}
        ev = normalize.normalize_engagement_row("summaries", row)
        self.assertEqual(ev["ai.engagement.daily_active_users"], 50)
        self.assertEqual(ev["ai.engagement.kind"], "summaries")
        self.assertEqual(ev["ai.event.created_at"], "2026-06-01")


if __name__ == "__main__":
    unittest.main()
