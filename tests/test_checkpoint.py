"""Unit tests for checkpoint persistence. Dev-only; exclude from packaging."""

import os
import sys
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(__file__), "..", "bin")
sys.path.insert(0, BIN)

from lib_cloud_llm.checkpoint import Checkpoint  # noqa: E402


class TestCheckpoint(unittest.TestCase):
    def test_roundtrip_and_advance(self):
        with tempfile.TemporaryDirectory() as d:
            ckpt = Checkpoint(d, "stanza://demo")
            self.assertEqual(ckpt.read(), {})
            ckpt.write({"last_id": "activity_1"})
            self.assertEqual(ckpt.read()["last_id"], "activity_1")
            ckpt.write({"last_id": "activity_2"})
            self.assertEqual(ckpt.read()["last_id"], "activity_2")

    def test_distinct_keys_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            a = Checkpoint(d, "key_a")
            b = Checkpoint(d, "key_b")
            a.write({"v": 1})
            b.write({"v": 2})
            self.assertEqual(a.read()["v"], 1)
            self.assertEqual(b.read()["v"], 2)


if __name__ == "__main__":
    unittest.main()
