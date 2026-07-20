#!/bin/bash
# Deploy build_out/ apps onto the local dev Splunk at /opt/splunk104.
#
#   build/deploy.sh [--dry-run] [--restart | --refresh]
#
# rsync --delete makes the live default/ an exact mirror of the build; the
# --exclude flags are LOAD-BEARING: local/ and metadata/local.meta hold instance
# state (credentials, configured inputs, enables, test-harness plumbing) and must
# survive every deploy. Never use --delete-excluded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_OUT="$REPO_ROOT/build_out"
SPLUNK_HOME=${SPLUNK_HOME:-/opt/splunk104}
APPS_DIR="$SPLUNK_HOME/etc/apps"

DRY=""
ACTION="none"
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY="-n" ;;
    --restart) ACTION="restart" ;;
    --refresh) ACTION="refresh" ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

[[ -d "$BUILD_OUT" ]] || { echo "build_out/ missing — run build/build.sh first" >&2; exit 1; }

for appdir in "$BUILD_OUT"/*/; do
  app=$(basename "$appdir")
  echo "deploy $app -> $APPS_DIR/$app ${DRY:+(dry-run)}"
  rsync -a --delete $DRY \
    --exclude 'local/' --exclude 'local.meta' --exclude '__pycache__' \
    "$appdir" "$APPS_DIR/$app/"
done

case "$ACTION" in
  restart) "$SPLUNK_HOME/bin/splunk" restart ;;
  refresh) echo "KO-only change: reload via https://localhost:8090/debug/refresh (or Settings > Refresh)" ;;
  none) [[ -n "$DRY" ]] || echo "deployed; restart splunkd to pick up bin/ or index-time changes" ;;
esac
