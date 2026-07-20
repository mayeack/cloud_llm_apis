#!/usr/bin/env python3
"""Generate expected ai.* fixtures by running the Anthropic adapter over raw
API-shaped fixtures — pure python, no Splunk.

    tests/generate_fixtures.py            regenerate tests/fixtures/anthropic/expected/
    tests/generate_fixtures.py --check    fail (exit 1) if expected/ is stale

raw/<kind>/*.jsonl holds one provider-API record per line; expected/<kind>/
gets the adapter's event JSON one per line. These expected files are both the
conformance oracle (test_adapter_conformance.py) and the spool payloads
(load_fixtures.sh). Snapshot records get a FIXED collection time so output is
deterministic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
sys.path.insert(0, str(REPO / "apps/TA-anthropic_claude_enterprise/package/bin"))

from ta_anthropic_claude_enterprise.adapter import AnthropicAdapter  # noqa: E402

FIXED_COLLECTED_AT = "2026-07-20T12:00:00Z"

RAW_DIR = REPO / "tests/fixtures/anthropic/raw"
EXPECTED_DIR = REPO / "tests/fixtures/anthropic/expected"

# kind directory -> (adapter method name, record/report type argument)
KIND_DISPATCH = {
    "compliance_activity": ("activity_event", None),
    "compliance_user": ("directory_event", "user"),
    "compliance_organization": ("directory_event", "organization"),
    "compliance_group": ("directory_event", "group"),
    "compliance_chat_content": ("directory_event", "chat"),
    "compliance_file_metadata": ("directory_event", "file"),
    "analytics_summary": ("analytics_event", "summary"),
    "analytics_usage": ("analytics_event", "usage"),
    "analytics_cost": ("analytics_event", "cost"),
    "analytics_user_usage": ("analytics_event", "user_usage"),
    "analytics_user_cost": ("analytics_event", "user_cost"),
    "analytics_user_activity": ("analytics_event", "user_activity"),
    "analytics_spend_limit": ("spend_limit_event", "spend_limit"),
    "analytics_spend_limit_request": ("spend_limit_event", "spend_limit_request"),
}


def convert(adapter: AnthropicAdapter, kind: str, record: dict) -> dict:
    method, arg = KIND_DISPATCH[kind]
    fn = getattr(adapter, method)
    return fn(record) if arg is None else fn(record, arg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify expected/ is current")
    args = parser.parse_args()

    adapter = AnthropicAdapter.default(collected_at=FIXED_COLLECTED_AT)
    stale = []
    for kind, _ in sorted(KIND_DISPATCH.items()):
        for raw_path in sorted((RAW_DIR / kind).glob("*.jsonl")):
            lines = [json.loads(l) for l in raw_path.read_text().splitlines() if l.strip()]
            events = [convert(adapter, kind, rec) for rec in lines]
            out = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
            out_path = EXPECTED_DIR / kind / raw_path.name
            if args.check:
                if not out_path.exists() or out_path.read_text() != out:
                    stale.append(str(out_path))
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(out)
                print(f"wrote {out_path.relative_to(REPO)} ({len(events)} events)")
    if args.check and stale:
        print("STALE expected fixtures (rerun tests/generate_fixtures.py):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
