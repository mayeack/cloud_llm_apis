#!/bin/bash
# Install the regression-test plumbing INTO THE MAIN APPS' local/ layer on the
# dev Splunk instance (no separate harness app — user decision). Idempotent:
# config lives inside BEGIN/END-marked blocks that this script replaces.
#
#   tests/setup_harness.sh        install/refresh harness config
#   (restart splunkd once after the first run so the index + monitors load)
#
# What it manages:
#   TA-ai-governance-indexes/local/indexes.conf  -> [ai_governance_test]
#   TA-anthropic_claude_enterprise/local/inputs.conf -> 14 file monitors over
#       /opt/splunk104/var/ai_governance_test_spool/anthropic/<kind>/
# No props are needed: the TA's default props read the events' own ai.time.
set -euo pipefail

SPLUNK_HOME=${SPLUNK_HOME:-/opt/splunk104}
SPOOL="$SPLUNK_HOME/var/ai_governance_test_spool/anthropic"
IDX_APP="$SPLUNK_HOME/etc/apps/TA-ai-governance-indexes"
TA_APP="$SPLUNK_HOME/etc/apps/TA-anthropic_claude_enterprise"
MARK=ai-governance-harness

[[ -d "$IDX_APP" && -d "$TA_APP" ]] || { echo "deploy the apps first (build/deploy.sh)" >&2; exit 1; }

KINDS=(
  "compliance_activity:anthropic:compliance:activity"
  "compliance_user:anthropic:compliance:user"
  "compliance_organization:anthropic:compliance:organization"
  "compliance_group:anthropic:compliance:group"
  "compliance_chat_content:anthropic:compliance:chat_content"
  "compliance_file_metadata:anthropic:compliance:file_metadata"
  "analytics_summary:anthropic:analytics:summary"
  "analytics_usage:anthropic:analytics:usage"
  "analytics_cost:anthropic:analytics:cost"
  "analytics_user_usage:anthropic:analytics:user_usage"
  "analytics_user_cost:anthropic:analytics:user_cost"
  "analytics_user_activity:anthropic:analytics:user_activity"
  "analytics_spend_limit:anthropic:analytics:spend_limit"
  "analytics_spend_limit_request:anthropic:analytics:spend_limit_request"
)

for entry in "${KINDS[@]}"; do
  mkdir -p "$SPOOL/${entry%%:*}"
done

INDEX_BLOCK="[ai_governance_test]
homePath = \$SPLUNK_DB/ai_governance_test/db
coldPath = \$SPLUNK_DB/ai_governance_test/colddb
thawedPath = \$SPLUNK_DB/ai_governance_test/thaweddb
maxTotalDataSizeMB = 2048
frozenTimePeriodInSecs = 2592000"

INPUTS_BLOCK=""
for entry in "${KINDS[@]}"; do
  kind="${entry%%:*}"
  st="${entry#*:}"
  INPUTS_BLOCK+="[monitor://$SPOOL/$kind]
index = ai_governance_test
sourcetype = $st
crcSalt = <SOURCE>
disabled = 0

"
done

replace_block() {  # file, block-content
  python3 - "$1" "$MARK" <<'PYEOF' "$2"
import sys
path, mark = sys.argv[1], sys.argv[2]
block = sys.argv[3].rstrip("\n")
begin, end = f"# BEGIN {mark}", f"# END {mark}"
try:
    text = open(path).read()
except FileNotFoundError:
    text = ""
if begin in text and end in text:
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    text = head.rstrip("\n") + ("\n\n" if head.strip() else "")
    tail = tail.lstrip("\n")
else:
    tail = ""
    text = text.rstrip("\n") + ("\n\n" if text.strip() else "")
with open(path, "w") as f:
    f.write(text + begin + "\n" + block + "\n" + end + "\n" + (tail and "\n" + tail))
print(f"harness block written: {path}")
PYEOF
}

mkdir -p "$IDX_APP/local" "$TA_APP/local"
replace_block "$IDX_APP/local/indexes.conf" "$INDEX_BLOCK"
replace_block "$TA_APP/local/inputs.conf" "$INPUTS_BLOCK"

echo "spool ready at $SPOOL"
echo "NOTE: restart splunkd once after the first install: $SPLUNK_HOME/bin/splunk restart"
