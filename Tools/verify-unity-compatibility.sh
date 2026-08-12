#!/usr/bin/env bash
# Run a clean-consumer compatibility attempt for every GameLovers package and Unity 6 reference editor.
#
# This script deliberately records attempts rather than inferring support from its exit code. A cell is
# only eligible to be called validated after its manifest, lock, compile logs, test XML, imported samples,
# and (where applicable) visual evidence have been reviewed.
#
# Usage:
#   Tools/verify-unity-compatibility.sh --run-id 20260812T120000Z
#   Tools/verify-unity-compatibility.sh --run-id 20260812T120000Z --package com.gamelovers.services
#   Tools/verify-unity-compatibility.sh --run-id 20260812T120000Z --editor 6000.0.81f1

set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
run_id=""
requested_package=""
requested_editor=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --run-id) run_id=${2:?missing run id}; shift 2 ;;
    --package) requested_package=${2:?missing package name}; shift 2 ;;
    --editor) requested_editor=${2:?missing editor version}; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -n "$run_id" ] || { echo "--run-id is required" >&2; exit 2; }

editors=(6000.0.81f1 6000.3.21f1 6000.5.7f1)
packages=(
  com.gamelovers.gamedata
  com.gamelovers.googlesheetimporter
  com.gamelovers.mobileservices
  com.gamelovers.services
  com.gamelovers.statechart
  com.gamelovers.uiservice
)

if [ -n "$requested_editor" ]; then editors=("$requested_editor"); fi
if [ -n "$requested_package" ]; then packages=("$requested_package"); fi

for package in "${packages[@]}"; do
  [ -f "$repo_root/Packages/$package/package.json" ] || { echo "Unknown package: $package" >&2; exit 2; }
done
for editor in "${editors[@]}"; do
  [ -x "/Applications/Unity/Hub/Editor/$editor/Unity.app/Contents/MacOS/Unity" ] || {
    echo "Editor not installed: $editor" >&2
    exit 2
  }
done

evidence_root="$repo_root/.compatibility-evidence/$run_id"
[ ! -e "$evidence_root" ] || { echo "Evidence already exists: $evidence_root" >&2; exit 2; }
mkdir -p "$evidence_root"

manifest_for() {
  local package=$1 output=$2
  python3 - "$package" "$output" <<'PY'
import json, sys
package, output = sys.argv[1:]
deps = {
    "com.unity.test-framework": "1.7.0",
}
git = {
    "com.gamelovers.gamedata": "https://github.com/CoderGamester/Unity-GameData.git#1.0.3",
    "com.gamelovers.googlesheetimporter": "https://github.com/CoderGamester/Unity-GoogleSheet-Importer.git#0.7.3",
    "com.gamelovers.mobileservices": "https://github.com/CoderGamester/Unity-MobileServices.git#1.0.1",
    "com.gamelovers.services": "https://github.com/CoderGamester/Unity-Services.git#2.1.2",
    "com.gamelovers.statechart": "https://github.com/CoderGamester/Statechart-HFSM.git#0.9.5",
    "com.gamelovers.uiservice": "https://github.com/CoderGamester/Unity-UiService.git#1.3.0",
}
if package not in git:
    raise SystemExit(f"Unknown package: {package}")
if package == "com.gamelovers.googlesheetimporter":
    deps["com.gamelovers.gamedata"] = git["com.gamelovers.gamedata"]
if package == "com.gamelovers.services":
    deps["com.gamelovers.gamedata"] = git["com.gamelovers.gamedata"]
    deps["com.cysharp.unitask"] = "https://github.com/Cysharp/UniTask.git?path=src/UniTask/Assets/Plugins/UniTask#2.5.10"
if package in ("com.gamelovers.statechart", "com.gamelovers.uiservice"):
    deps["com.cysharp.unitask"] = "https://github.com/Cysharp/UniTask.git?path=src/UniTask/Assets/Plugins/UniTask#2.5.10"
deps[package] = git[package]
json.dump({"dependencies": deps, "testables": [package]}, open(output, "w"), indent=2)
PY
}

copy_samples() {
  local host=$1 package=$2 log=$3
  local cache
  cache=$(find "$host/Library/PackageCache" -maxdepth 1 -type d -name "${package}@*" -print -quit)
  if [ -z "$cache" ]; then
    echo "sample import skipped: package cache not found" >> "$log"
    return 1
  fi
  if [ ! -d "$cache/Samples~" ]; then
    echo "sample import: package contains no Samples~ directory" >> "$log"
    return 0
  fi
  mkdir -p "$host/Assets/CompatibilitySamples/$package"
  rsync -a "$cache/Samples~/" "$host/Assets/CompatibilitySamples/$package/"
  echo "sample import: copied $cache/Samples~" >> "$log"
}

run_tests() {
  local unity=$1 host=$2 mode=$3 results=$4 log=$5
  rm -f "$results"
  "$unity" -batchmode -nographics -runTests -projectPath "$host" -testPlatform "$mode" \
    -testResults "$results" -logFile "$log" || true
  [ -s "$results" ] || return 1
  python3 - "$results" <<'PY'
import sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
print("total={total} passed={passed} failed={failed}".format(**root.attrib))
raise SystemExit(0 if root.get("failed") == "0" else 1)
PY
}

workspace_code_id() {
  { find "$repo_root/Packages" -type f \( -name '*.cs' -o -name '*.asmdef' -o -name package.json \) -print0 | sort -z | xargs -0 shasum; } | shasum | cut -c1-12
}

for package in "${packages[@]}"; do
  for editor in "${editors[@]}"; do
    unity="/Applications/Unity/Hub/Editor/$editor/Unity.app/Contents/MacOS/Unity"

    cell="$evidence_root/$package/$editor"
    mkdir -p "$cell"
    host=$(mktemp -d "${TMPDIR:-/tmp}/gamelovers-compat.${package##*.}.${editor}.XXXXXX")
    printf 'package=%s\neditor=%s\nworkspace_code_id=%s\nstarted_utc=%s\n' \
      "$package" "$editor" "$(workspace_code_id)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$cell/metadata.txt"

    mkdir -p "$host/Assets" "$host/Packages"
    cp -R "$repo_root/ProjectSettings" "$host/ProjectSettings"
    printf 'm_EditorVersion: %s\nm_EditorVersionWithRevision: %s\n' "$editor" "$editor" > "$host/ProjectSettings/ProjectVersion.txt"
    manifest_for "$package" "$host/Packages/manifest.json"
    cp "$host/Packages/manifest.json" "$cell/manifest.json"

    compile_log="$cell/compile.log"
    "$unity" -batchmode -nographics -quit -projectPath "$host" -logFile "$compile_log" || true
    if [ -f "$host/Packages/packages-lock.json" ]; then cp "$host/Packages/packages-lock.json" "$cell/packages-lock.json"; fi
    if rg -q 'Scripts have compiler errors|error CS[0-9]+' "$compile_log"; then
      echo "compile=failed" >> "$cell/metadata.txt"
      continue
    fi
    echo "compile=completed" >> "$cell/metadata.txt"

    sample_log="$cell/samples.log"
    if ! copy_samples "$host" "$package" "$sample_log"; then
      echo "samples=not-imported" >> "$cell/metadata.txt"
      continue
    fi
    "$unity" -batchmode -nographics -quit -projectPath "$host" -logFile "$cell/sample-compile.log" || true
    if rg -q 'Scripts have compiler errors|error CS[0-9]+' "$cell/sample-compile.log"; then
      echo "samples=compile-failed" >> "$cell/metadata.txt"
      continue
    fi
    echo "samples=compile-completed" >> "$cell/metadata.txt"

    run_tests "$unity" "$host" EditMode "$cell/editmode.xml" "$cell/editmode.log" && echo "editmode=passed" >> "$cell/metadata.txt" || echo "editmode=not-passed" >> "$cell/metadata.txt"
    run_tests "$unity" "$host" PlayMode "$cell/playmode.xml" "$cell/playmode.log" && echo "playmode=passed" >> "$cell/metadata.txt" || echo "playmode=not-passed" >> "$cell/metadata.txt"
    printf 'completed_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$cell/metadata.txt"
  done
done

cat <<EOF
Compatibility attempts written to: $evidence_root
Review every metadata file and its non-empty artifacts. UI Service still needs an Editor PlayMode run and inspected URP screenshots; this batch runner cannot establish visual compatibility.
EOF
