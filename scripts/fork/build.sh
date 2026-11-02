#!/usr/bin/env bash
# Builds the fork: a Release Ardia.app with no updater (apps/browser/macos/Fork.xcconfig),
# signed ad hoc, on the prebuilt engine from the upstream releases. No Chromium build, no notarization.
#
#   scripts/fork/build.sh [<output dir>]    (default: dist/fork)
#   scripts/fork/build.sh -h | --help
#
# Leaves "Ardia Fork.app" and Ardia-Fork.zip in the output dir and prints `app: <path>` last.
# The full xcodebuild log: apps/browser/build-fork/build.log.
set -euo pipefail

case "${1:-}" in
  -h | --help) awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
esac

root=$(cd "$(dirname "$0")/../.." && pwd -P)
mkdir -p "${1:-$root/dist/fork}"
out=$(cd "${1:-$root/dist/fork}" && pwd -P)
build="$root/apps/browser/build-fork"
locked="$root/scripts/agent/locked"
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

echo "==> Engine"
framework=$("$root/packages/ardiacore/scripts/fetch-engine.sh" --nearest)
export ARDIACORE_FRAMEWORK="$framework"

echo "==> Dependencies"
"$locked" pod --wait 1800 -- pnpm -C "$root" install --frozen-lockfile
(cd "$root/apps/browser/macos" && "$locked" pod --wait 1800 -- pod install)
"$root/packages/ardiacore/scripts/ubo.sh"

echo "==> Build"
mkdir -p "$build"
(cd "$root/apps/browser" && "$locked" xcodebuild --wait 1800 -- xcodebuild -workspace macos/Ardia.xcworkspace \
  -scheme Ardia-macOS -configuration Release -destination 'generic/platform=macOS' ARCHS=arm64 \
  ARDIACORE_STAGE_DIR="$build/ArdiaCoreFramework" -derivedDataPath "$build" -xcconfig macos/Fork.xcconfig build) \
  > "$build/build.log" 2>&1 || {
  grep -E "error:|build commands failed" -A2 "$build/build.log" | tail -20 >&2
  echo "error: the build failed ($build/build.log)" >&2
  exit 1
}

app="$out/Ardia Fork.app"
rm -rf "$app" "$out/Ardia-Fork.zip"
ditto "$build/Build/Products/Release/Ardia.app" "$app"
ditto -c -k --keepParent "$app" "$out/Ardia-Fork.zip"
echo "app: $app"
