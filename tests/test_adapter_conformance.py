#!/usr/bin/env python3
"""Adapter conformance suite — the contract test every provider adapter must
pass (docs/ai-schema.md). Pure python, no Splunk. Runs under pytest OR
standalone: python3 tests/test_adapter_conformance.py

Checks, per raw fixture record:
  1. adapter(raw) equals the committed expected event byte-for-byte when
     serialized (this also pins key ORDER: ai first, time first inside ai);
  2. required envelope fields present; activity records carry the
     event_type/event_id/action/outcome quartet;
  3. closed vocabularies respected (category/record/action/outcome/resource);
  4. no null values and no literal "null" strings anywhere;
  5. cost fields are USD floats (cents never leak through).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
sys.path.insert(0, str(REPO / "apps/TA-anthropic_claude_enterprise/package/bin"))
sys.path.insert(0, str(REPO / "tests"))

from ai_common import schema  # noqa: E402
from generate_fixtures import FIXED_COLLECTED_AT, KIND_DISPATCH, RAW_DIR, EXPECTED_DIR, convert  # noqa: E402
from ta_anthropic_claude_enterprise.adapter import AnthropicAdapter  # noqa: E402


def iter_cases():
    adapter = AnthropicAdapter.default(collected_at=FIXED_COLLECTED_AT)
    for kind in sorted(KIND_DISPATCH):
        for raw_path in sorted((RAW_DIR / kind).glob("*.jsonl")):
            expected_path = EXPECTED_DIR / kind / raw_path.name
            raw_lines = [l for l in raw_path.read_text().splitlines() if l.strip()]
            expected_lines = [l for l in expected_path.read_text().splitlines() if l.strip()]
            assert len(raw_lines) == len(expected_lines), f"{raw_path}: raw/expected length mismatch"
            for i, (raw_line, expected_line) in enumerate(zip(raw_lines, expected_lines)):
                yield adapter, kind, f"{kind}/{raw_path.name}[{i}]", json.loads(raw_line), expected_line


def walk(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, value


def check_contract(case: str, event: dict) -> None:
    assert list(event)[0] == "ai", f"{case}: 'ai' must be the first event key"
    ai = event["ai"]
    assert list(ai)[0] == "time", f"{case}: 'time' must be the first ai key"
    for field in schema.REQUIRED_ENVELOPE:
        assert ai.get(field) not in (None, ""), f"{case}: missing ai.{field}"
    assert ai["schema_version"] == schema.SCHEMA_VERSION, case
    assert ai["vendor"] in schema.VENDORS, case
    assert ai["record"] in schema.RECORDS, case
    assert ai["event_category"] in schema.CATEGORIES, case
    if ai["record"] == schema.RECORD_ACTIVITY:
        for field in schema.REQUIRED_ACTIVITY:
            assert ai.get(field) not in (None, ""), f"{case}: activity missing ai.{field}"
        assert ai["action"] in schema.ACTIONS, case
        assert ai["outcome"] in schema.OUTCOMES, case
    else:
        assert ai["event_category"] == schema.RECORD_CATEGORY[ai["record"]], case
    resource = ai.get("resource")
    if resource and resource.get("type"):
        assert resource["type"] in schema.RESOURCE_TYPES, case
    for path, value in walk(event):
        assert value is not None, f"{case}: null at {path}"
        assert value != "null", f"{case}: literal 'null' string at {path}"
    for key, value in (ai.get("cost") or {}).items():
        if key.endswith("_usd") or key.endswith("_pct"):
            assert isinstance(value, (int, float)), f"{case}: ai.cost.{key} not numeric"
            assert not isinstance(value, str), case


def test_conformance():
    count = 0
    for adapter, kind, case, raw, expected_line in iter_cases():
        actual = convert(adapter, kind, raw)
        assert json.dumps(actual, ensure_ascii=False) == expected_line, (
            f"{case}: adapter output differs from committed expected fixture "
            f"(if the change is intentional, rerun tests/generate_fixtures.py)"
        )
        check_contract(case, actual)
        count += 1
    assert count > 0, "no fixtures found"
    print(f"conformance: {count} events checked")


def test_record_category_map_is_total():
    assert schema.RECORDS - {schema.RECORD_ACTIVITY} == set(schema.RECORD_CATEGORY)


if __name__ == "__main__":
    test_record_category_map_is_total()
    test_conformance()
    print("ADAPTER CONFORMANCE: PASS")
