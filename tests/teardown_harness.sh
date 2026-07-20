#!/bin/bash
# Remove the harness config blocks that setup_harness.sh installed in the main
# apps' local/ layer, and the fixture spool. Indexed test data ages out with
# the index (or delete the ai_governance_test index dir after a stop).
set -euo pipefail

SPLUNK_HOME=${SPLUNK_HOME:-/opt/splunk104}
MARK=ai-governance-harness

for f in "$SPLUNK_HOME/etc/apps/TA-ai-governance-indexes/local/indexes.conf" \
         "$SPLUNK_HOME/etc/apps/TA-anthropic_claude_enterprise/local/inputs.conf"; do
  [[ -f "$f" ]] || continue
  python3 - "$f" "$MARK" <<'PYEOF'
import sys
path, mark = sys.argv[1], sys.argv[2]
begin, end = f"# BEGIN {mark}", f"# END {mark}"
text = open(path).read()
if begin in text and end in text:
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    out = head.rstrip("\n") + "\n" + tail.lstrip("\n")
    out = out.strip("\n")
    with open(path, "w") as f:
        f.write(out + "\n" if out else "")
    print(f"harness block removed: {path}")
else:
    print(f"no harness block in {path}")
PYEOF
done

rm -rf "$SPLUNK_HOME/var/ai_governance_test_spool"
echo "spool removed; restart splunkd to drop the monitors"
