"""KV Store checkpointing (SHC-safe), provider-neutral.

The collection name is part of each TA's identity and must be passed in — it
keys stored input state, so sharing or renaming it orphans checkpoints.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from solnlib.modular_input import checkpointer


class CheckpointStore:
    """Persist input checkpoints in Splunk KV Store (SHC-safe)."""

    def __init__(self, session_key: str, addon_name: str, collection_name: str):
        self._checkpointer = checkpointer.KVStoreCheckpointer(
            collection_name,
            session_key,
            addon_name,
        )

    def get(self, input_key: str) -> Dict[str, Any]:
        state = self._checkpointer.get(input_key)
        if not state:
            return {}
        if isinstance(state, dict):
            return state
        return {}

    def set(self, input_key: str, state: Dict[str, Any]) -> None:
        self._checkpointer.update(input_key, state)

    def get_value(self, input_key: str, field: str, default: Optional[Any] = None) -> Any:
        return self.get(input_key).get(field, default)

    def update(self, input_key: str, **fields: Any) -> Dict[str, Any]:
        state = self.get(input_key)
        state.update(fields)
        self.set(input_key, state)
        return state
