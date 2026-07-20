#!/bin/bash
# Load the expected ai.* fixtures into the dev instance's ai_governance_test
# index via the spool monitors that setup_harness.sh installed.
#
# Each run gets a fresh RUN_ID: it is stamped into every event (raw.test_run_id)
# so assertions are run-scoped, and into the filename so crcSalt=<SOURCE>
# re-ingests. Prints RUN_ID on the last line for run_regression.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPLUNK_HOME=${SPLUNK_HOME:-/opt/splunk104}
SPOOL="$SPLUNK_HOME/var/ai_governance_test_spool/anthropic"
EXPECTED="$REPO_ROOT/tests/fixtures/anthropic/expected"
RUN_ID="run$(date +%s)"

[[ -d "$SPOOL" ]] || { echo "spool missing — run tests/setup_harness.sh first" >&2; exit 1; }

count=0
for dir in "$EXPECTED"/*/; do
  kind=$(basename "$dir")
  mkdir -p "$SPOOL/$kind"
  for f in "$dir"*.jsonl; do
    [[ -e "$f" ]] || continue
    out="$SPOOL/$kind/$(basename "${f%.jsonl}").$RUN_ID.json"
    python3 - "$f" "$out" "$RUN_ID" <<'PYEOF'
import json, sys
src, dst, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src) as fin, open(dst, "w") as fout:
    for line in fin:
        if not line.strip():
            continue
        event = json.loads(line)
        event.setdefault("raw", {})["test_run_id"] = run_id
        fout.write(json.dumps(event, ensure_ascii=False) + "\n")
PYEOF
    count=$((count+1))
  done
done

echo "loaded $count fixture files into $SPOOL"
echo "$RUN_ID"
