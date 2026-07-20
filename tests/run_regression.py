#!/usr/bin/env python3
"""Dashboard/saved-search regression runner for the AI governance suite.

Extracts every panel <query> from the SA dashboards plus the TA's
claude_code_mcp dashboard (claude_ta_health is skipped: its panels are
_internal log queries), rewrites the index macros onto the ai_governance_test
index, scopes to one fixture load via raw.test_run_id, dispatches each search
against the dev instance's management port, and asserts row-count expectations
from tests/expected.json.

    tests/run_regression.py --run-id run1784...      assert against expected.json
    tests/run_regression.py --run-id ... --seed      print an expected.json skeleton
                                                     with observed counts (review, then save)

Auth (management port, default https://localhost:8090):
    SPLUNK_TOKEN=<token>  or  SPLUNK_USERNAME=<u> SPLUNK_PASSWORD=<p>
The splunk104 MCP server is read-only and cannot dispatch scripted jobs — this
runner talks REST directly.

Exit codes: 0 all pass · 1 assertion failures · 2 coverage gap (a panel or
saved search has no entry in expected.json — every migrated panel must be
covered) · 3 environment/auth errors.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXPECTED_PATH = REPO / "tests/expected.json"
TEST_INDEX_EXPR = "(index=ai_governance_test)"

DASHBOARDS = [
    REPO / "apps/SA-ai-governance/default/data/ui/views/ai_governance_overview.xml",
    REPO / "apps/SA-ai-governance/default/data/ui/views/ai_governance_security_audit.xml",
    REPO / "apps/SA-ai-governance/default/data/ui/views/ai_governance_tokenomics.xml",
    REPO / "apps/TA-anthropic_claude_enterprise/package/default/data/ui/views/claude_code_mcp.xml",
]
SAVEDSEARCHES = REPO / "apps/SA-ai-governance/default/savedsearches.conf"

MACRO_RE = re.compile(r"`(?:ai_governance_index|anthropic_claude_index)`")
TOKEN_RE = re.compile(r"\$([A-Za-z0-9_.]+)\$")


def rewrite(query: str, run_id: str) -> str:
    q = MACRO_RE.sub(TEST_INDEX_EXPR, query)
    q = q.replace("$provider$", "*")
    q = TOKEN_RE.sub("*", q)  # any remaining dashboard tokens -> wildcard
    if not q.lstrip().startswith("|"):
        # scope the base search to this fixture load
        q = q.replace(TEST_INDEX_EXPR, f'{TEST_INDEX_EXPR} "raw.test_run_id"={run_id}', 1)
    return q


def panel_queries(path: Path):
    """Yield (key, query) for panel searches; skips <input> populator searches."""
    root = ET.parse(path).getroot()
    inputs = {id(q) for inp in root.iter("input") for q in inp.iter("query")}
    idx = 0
    for panel in list(root.iter("panel")):
        title_el = panel.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        for q in panel.iter("query"):
            if id(q) in inputs or q.text is None:
                continue
            key = f"{path.stem}#{idx:02d} {title}".strip()
            yield key, q.text
            idx += 1


def saved_searches(path: Path):
    text = path.read_text()
    text = text.replace("\\\n", " ")
    stanza, search = None, None
    for line in text.splitlines():
        m = re.match(r"\[(.+)\]\s*$", line)
        if m:
            stanza = m.group(1)
        elif stanza and line.startswith("search ="):
            yield f"savedsearch:{stanza}", line.split("=", 1)[1].strip()


class Splunk:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.ctx = ssl._create_unverified_context()
        token = os.environ.get("SPLUNK_TOKEN")
        if token:
            self.auth = f"Bearer {token}"
        else:
            user = os.environ.get("SPLUNK_USERNAME")
            password = os.environ.get("SPLUNK_PASSWORD")
            if not (user and password):
                print("set SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD", file=sys.stderr)
                sys.exit(3)
            cred = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.auth = f"Basic {cred}"

    def oneshot(self, query: str) -> int:
        q = query if query.lstrip().startswith("|") else "search " + query
        body = urllib.parse.urlencode(
            {
                "search": q,
                "exec_mode": "oneshot",
                "output_mode": "json",
                "count": 0,
                "earliest_time": "1",
                "latest_time": "now",
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/services/search/jobs",
            data=body,
            headers={"Authorization": self.auth},
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
            payload = json.load(resp)
        return len(payload.get("results", []))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True, help="RUN_ID printed by load_fixtures.sh")
    parser.add_argument("--base-url", default="https://localhost:8090")
    parser.add_argument("--seed", action="store_true", help="print observed counts as an expected.json skeleton")
    args = parser.parse_args()

    cases = []
    for dash in DASHBOARDS:
        if not dash.exists():
            print(f"missing dashboard: {dash}", file=sys.stderr)
            return 3
        cases.extend(panel_queries(dash))
    cases.extend(saved_searches(SAVEDSEARCHES))

    splunk = Splunk(args.base_url)
    observed = {}
    for key, query in cases:
        try:
            observed[key] = splunk.oneshot(rewrite(query, args.run_id))
        except Exception as exc:  # keep going; report at the end
            observed[key] = f"ERROR: {exc}"

    if args.seed:
        print(json.dumps({k: {"min_rows": (v if isinstance(v, int) else 0)} for k, v in observed.items()}, indent=2))
        return 0

    if not EXPECTED_PATH.exists():
        print("tests/expected.json missing — run with --seed to create it", file=sys.stderr)
        return 2
    expected = json.loads(EXPECTED_PATH.read_text())

    uncovered = [k for k in observed if k not in expected]
    failures = []
    for key, rows in observed.items():
        want = expected.get(key)
        if want is None:
            continue
        ok = isinstance(rows, int) and (
            ("rows" in want and rows == want["rows"]) or ("min_rows" in want and rows >= want["min_rows"])
        )
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures.append(key)
        print(f"{status}  {key}  rows={rows} expected={want}")

    if uncovered:
        print("\nCOVERAGE GAP — no expectation for:", *uncovered, sep="\n  ")
        return 2
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print(f"\nall {len(observed)} checks passed (run {args.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
