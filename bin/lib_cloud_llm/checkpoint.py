"""Per-stanza checkpoint storage for the modular inputs.

State is written as JSON into the checkpoint_dir Splunk passes to each input.
Filenames are derived from a stable checkpoint key so re-runs and restarts
resume instead of re-ingesting.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile


class Checkpoint:
    def __init__(self, checkpoint_dir, key):
        self._dir = checkpoint_dir
        safe = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        self._path = os.path.join(checkpoint_dir, "ckpt_%s.json" % safe)

    def read(self):
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, ValueError):
            return {}

    def write(self, state):
        # Atomic write so a crash mid-write cannot corrupt the checkpoint.
        os.makedirs(self._dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=".ckpt_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
