"""Shared helpers for the TA-cloud_llm_apis modular inputs.

Provider-neutral building blocks: an HTTPS-only HTTP client with retry/backoff,
the Anthropic -> ai.* normalizer, per-stanza checkpointing, and secret storage
backed by Splunk's encrypted storage/passwords.
"""

PROVIDER = "anthropic"
USER_AGENT = "TA-cloud_llm_apis/1.0"
