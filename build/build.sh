#!/bin/bash
# Build all apps into build_out/ and package release tarballs into dist/.
#
#   build/build.sh            build + package everything
#   build/build.sh --no-dist  build only (skip tarballs)
#
# TA-anthropic_claude_enterprise is UCC-generated from its package/ source, then
# shared/ai_common is copied into its bin/ (apps must be runtime-self-contained:
# Splunk apps cannot reliably import python across apps). SA-ai-governance and
# TA-ai-governance-indexes are plain apps copied verbatim.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UCC_GEN="$REPO_ROOT/.venv/bin/ucc-gen"
BUILD_OUT="$REPO_ROOT/build_out"
DIST="$REPO_ROOT/dist"
TA=TA-anthropic_claude_enterprise

[[ -x "$UCC_GEN" ]] || { echo "ucc-gen not found — run: python3 -m venv .venv && .venv/bin/pip install 'splunk-add-on-ucc-framework==6.5.1'" >&2; exit 1; }

rm -rf "$BUILD_OUT"
mkdir -p "$BUILD_OUT" "$DIST"

# --- TA: ucc-gen build ---------------------------------------------------------
TA_VERSION=$(python3 -c "import json;print(json.load(open('$REPO_ROOT/apps/$TA/globalConfig.json'))['meta']['version'])")
(
  cd "$REPO_ROOT/apps/$TA"
  "$UCC_GEN" build --source package --config globalConfig.json --ta-version "$TA_VERSION" >/dev/null
)
rsync -a --delete "$REPO_ROOT/apps/$TA/output/$TA/" "$BUILD_OUT/$TA/"
rsync -a --delete "$REPO_ROOT/shared/ai_common/" "$BUILD_OUT/$TA/bin/ai_common/"
find "$BUILD_OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "built $TA $TA_VERSION (ucc-gen + ai_common)"

# --- plain apps: verbatim copy -------------------------------------------------
for app in SA-ai-governance TA-ai-governance-indexes; do
  if [[ -d "$REPO_ROOT/apps/$app" ]]; then
    rsync -a --delete --exclude 'local/' --exclude 'local.meta' "$REPO_ROOT/apps/$app/" "$BUILD_OUT/$app/"
    echo "built $app"
  else
    echo "skipping $app (not present yet)"
  fi
done

# --- package -------------------------------------------------------------------
if [[ "${1:-}" != "--no-dist" ]]; then
  for appdir in "$BUILD_OUT"/*/; do
    app=$(basename "$appdir")
    if [[ "$app" == "$TA" ]]; then
      version="$TA_VERSION"
    else
      version=$(sed -n 's/^version *= *//p' "$appdir/default/app.conf" | head -1)
    fi
    tarball="$DIST/$app-${version:-0.0.0}.tar.gz"
    COPYFILE_DISABLE=1 tar --no-xattrs -czf "$tarball" -C "$BUILD_OUT" "$app"
    echo "packaged $(basename "$tarball")"
  done
fi
