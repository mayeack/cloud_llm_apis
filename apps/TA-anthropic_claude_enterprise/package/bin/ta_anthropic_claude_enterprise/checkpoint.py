"""Thin binding of ai_common.checkpoint to this add-on's KV collection."""

from __future__ import annotations

from ai_common.checkpoint import CheckpointStore as _SharedCheckpointStore

from ta_anthropic_claude_enterprise import ADDON_NAME, CHECKPOINT_COLLECTION


class CheckpointStore(_SharedCheckpointStore):
    def __init__(self, session_key: str, collection_name: str = CHECKPOINT_COLLECTION):
        super().__init__(session_key, ADDON_NAME, collection_name)
