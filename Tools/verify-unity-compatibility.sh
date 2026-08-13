#!/usr/bin/env bash
# Record clean-consumer compatibility attempts for current source and published installation manifests.
# This runner cannot close visual, native-platform, fixture-output, or Editor-only gates by itself.

set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
run_id=""
requested_package=""
requested_editor=""
requested_mode="both"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --run-id) run_id=${2:?missing run id}; shift 2 ;;
    --package) requested_package=${2:?missing package name}; shift 2 ;;
    --editor) requested_editor=${2:?missing editor version}; shift 2 ;;
    --mode) requested_mode=${2:?missing mode}; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -n "$run_id" ] || { echo "--run-id is required" >&2; exit 2; }
case "$requested_mode" in source|published|both) ;; *) echo "--mode must be source, published, or both" >&2; exit 2 ;; esac

editors=(6000.0.81f1 6000.3.21f1 6000.5.7f1)
packages=(
  com.gamelovers.gamedata
  com.gamelovers.googlesheetimporter
  com.gamelovers.mobileservices
  com.gamelovers.services
  com.gamelovers.statechart
  com.gamelovers.uiservice
)
modes=(source published)

[ -z "$requested_editor" ] || editors=("$requested_editor")
[ -z "$requested_package" ] || packages=("$requested_package")
[ "$requested_mode" = both ] || modes=("$requested_mode")

for package in "${packages[@]}"; do
  [ -f "$repo_root/Packages/$package/package.json" ] || { echo "Unknown package: $package" >&2; exit 2; }
done
for editor in "${editors[@]}"; do
  [ -x "/Applications/Unity/Hub/Editor/$editor/Unity.app/Contents/MacOS/Unity" ] || {
    echo "Editor not installed: $editor" >&2
    exit 2
  }
done

evidence_root="$repo_root/.test-all/compatibility/$run_id"
[ ! -e "$evidence_root" ] || { echo "Evidence already exists: $evidence_root" >&2; exit 2; }
mkdir -p "$evidence_root"

manifest_for() {
  local package=$1 output=$2 mode=$3
  python3 - "$package" "$output" "$mode" "$repo_root" <<'PY'
import json, pathlib, sys
package, output, mode, root = sys.argv[1:]
git = {
    "com.gamelovers.gamedata": "https://github.com/CoderGamester/Unity-GameData.git#1.0.3",
    "com.gamelovers.googlesheetimporter": "https://github.com/CoderGamester/Unity-GoogleSheet-Importer.git#0.7.3",
    "com.gamelovers.mobileservices": "https://github.com/CoderGamester/Unity-MobileServices.git#1.0.1",
    "com.gamelovers.services": "https://github.com/CoderGamester/Unity-Services.git#2.1.2",
    "com.gamelovers.statechart": "https://github.com/CoderGamester/Statechart-HFSM.git#0.9.5",
    "com.gamelovers.uiservice": "https://github.com/CoderGamester/Unity-UiService.git#1.3.0",
}
deps = {"com.unity.test-framework": "1.7.0"}
if package == "com.gamelovers.googlesheetimporter":
    deps["com.gamelovers.gamedata"] = git["com.gamelovers.gamedata"]
if package == "com.gamelovers.services":
    deps["com.gamelovers.gamedata"] = git["com.gamelovers.gamedata"]
if package in ("com.gamelovers.services", "com.gamelovers.statechart", "com.gamelovers.uiservice"):
    deps["com.cysharp.unitask"] = "https://github.com/Cysharp/UniTask.git?path=src/UniTask/Assets/Plugins/UniTask#2.5.10"
deps[package] = (pathlib.Path(root) / "Packages" / package).as_uri() if mode == "source" else git[package]
with open(output, "w", encoding="utf-8") as handle:
    json.dump({"dependencies": deps, "testables": [package]}, handle, indent=2)
    handle.write("\n")
PY
}

package_code_id() {
  local package=$1
  find "$repo_root/Packages/$package" -type f \( -name '*.cs' -o -name '*.asmdef' -o -name package.json \) -print0 |
    sort -z | xargs -0 shasum | shasum | cut -c1-12
}

copy_declared_samples() {
  local host=$1 package=$2 mode=$3 log=$4 base=""
  if [ "$mode" = source ]; then
    base="$repo_root/Packages/$package"
  else
    base=$(find "$host/Library/PackageCache" -maxdepth 1 -type d -name "${package}@*" -print -quit)
  fi
  if [ -z "$base" ] || [ ! -f "$base/package.json" ]; then
    echo "sample import: installed package source not found" >> "$log"
    return 2
  fi
  local count=0
  while IFS= read -r relative; do
    [ -n "$relative" ] || continue
    count=$((count + 1))
    if [ ! -d "$base/$relative" ]; then
      echo "sample import: declared path missing: $relative" >> "$log"
      return 1
    fi
    local destination="$host/Assets/CompatibilitySamples/$package/$(basename "$relative")"
    mkdir -p "$(dirname "$destination")"
    rsync -a "$base/$relative/" "$destination/"
    echo "sample import: $relative -> $destination" >> "$log"
  done < <(python3 - "$base/package.json" <<'PY'
import json, sys
for sample in json.load(open(sys.argv[1], encoding="utf-8-sig")).get("samples", []):
    print(sample["path"])
PY
)
  echo "sample import count=$count" >> "$log"
}

run_unity() {
  local unity=$1 host=$2 log=$3
  shift 3
  rm -f "$log"
  set +e
  "$unity" -batchmode -nographics -projectPath "$host" "$@" -logFile "$log"
  local status=$?
  set -e
  [ -s "$log" ] || return 125
  return "$status"
}

run_tests() {
  local unity=$1 host=$2 mode=$3 results=$4 log=$5
  rm -f "$results"
  run_unity "$unity" "$host" "$log" -runTests -testPlatform "$mode" -testResults "$results" || return $?
  [ -s "$results" ] || return 125
  python3 - "$results" <<'PY'
import sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
print("total={total} passed={passed} failed={failed}".format(**root.attrib))
raise SystemExit(0 if root.get("failed") == "0" else 1)
PY
}

record_bytes() {
  local cell=$1
  find "$cell" -type f ! -name artifact-bytes.txt -exec wc -c {} \; > "$cell/artifact-bytes.txt"
}

for package in "${packages[@]}"; do
  for editor in "${editors[@]}"; do
    for mode in "${modes[@]}"; do
      unity="/Applications/Unity/Hub/Editor/$editor/Unity.app/Contents/MacOS/Unity"
      cell="$evidence_root/$package/$editor/$mode"
      mkdir -p "$cell"
      host=$(mktemp -d "${TMPDIR:-/tmp}/gamelovers-compat.${package##*.}.${editor}.${mode}.XXXXXX")
      installed="file:$repo_root/Packages/$package"
      identity="workspace_code_id=$(package_code_id "$package")"
      if [ "$mode" = published ]; then
        installed="pinned README Git URL in manifest.json"
        identity="workspace_code_id=NOT_APPLICABLE"
      fi
      printf 'package=%s\neditor=%s\nmode=%s\ninstalled_source=%s\n%s\nstarted_utc=%s\noverall_status=NOT_VALIDATED\n' \
        "$package" "$editor" "$mode" "$installed" "$identity" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$cell/metadata.txt"

      mkdir -p "$host/Assets" "$host/Packages" "$host/ProjectSettings"
      printf 'm_EditorVersion: %s\n' "$editor" > "$host/ProjectSettings/ProjectVersion.txt"
      manifest_for "$package" "$host/Packages/manifest.json" "$mode"
      cp "$host/Packages/manifest.json" "$cell/manifest.json"

      compile_log="$cell/compile.log"
      if ! run_unity "$unity" "$host" "$compile_log" -quit; then
        if rg -q 'Scripts have compiler errors|error CS[0-9]+' "$compile_log"; then
          echo "compile=FAILED" >> "$cell/metadata.txt"
          sed -i '' 's/overall_status=NOT_VALIDATED/overall_status=FAILED/' "$cell/metadata.txt"
        else
          echo "compile=NOT_VALIDATED" >> "$cell/metadata.txt"
        fi
        [ ! -f "$host/Packages/packages-lock.json" ] || cp "$host/Packages/packages-lock.json" "$cell/packages-lock.json"
        record_bytes "$cell"
        continue
      fi
      if rg -q 'Scripts have compiler errors|error CS[0-9]+' "$compile_log"; then
        echo "compile=FAILED" >> "$cell/metadata.txt"
        sed -i '' 's/overall_status=NOT_VALIDATED/overall_status=FAILED/' "$cell/metadata.txt"
        [ ! -f "$host/Packages/packages-lock.json" ] || cp "$host/Packages/packages-lock.json" "$cell/packages-lock.json"
        record_bytes "$cell"
        continue
      fi
      if [ ! -s "$host/Packages/packages-lock.json" ]; then
        echo "compile=NOT_VALIDATED" >> "$cell/metadata.txt"
        record_bytes "$cell"
        continue
      fi
      cp "$host/Packages/packages-lock.json" "$cell/packages-lock.json"
      echo "compile=PASSED" >> "$cell/metadata.txt"

      sample_log="$cell/samples.log"
      if ! copy_declared_samples "$host" "$package" "$mode" "$sample_log"; then
        echo "samples=FAILED" >> "$cell/metadata.txt"
        sed -i '' 's/overall_status=NOT_VALIDATED/overall_status=FAILED/' "$cell/metadata.txt"
        record_bytes "$cell"
        continue
      fi
      if ! run_unity "$unity" "$host" "$cell/sample-compile.log" -quit; then
        if rg -q 'Scripts have compiler errors|error CS[0-9]+' "$cell/sample-compile.log"; then
          echo "samples=FAILED" >> "$cell/metadata.txt"
          sed -i '' 's/overall_status=NOT_VALIDATED/overall_status=FAILED/' "$cell/metadata.txt"
        else
          echo "samples=NOT_VALIDATED" >> "$cell/metadata.txt"
        fi
        record_bytes "$cell"
        continue
      fi
      if rg -q 'Scripts have compiler errors|error CS[0-9]+' "$cell/sample-compile.log"; then
        echo "samples=FAILED" >> "$cell/metadata.txt"
        sed -i '' 's/overall_status=NOT_VALIDATED/overall_status=FAILED/' "$cell/metadata.txt"
        record_bytes "$cell"
        continue
      fi
      echo "samples=PASSED" >> "$cell/metadata.txt"

      edit_status=PASSED
      run_tests "$unity" "$host" EditMode "$cell/editmode.xml" "$cell/editmode.log" || edit_status=$([ -s "$cell/editmode.xml" ] && echo FAILED || echo NOT_VALIDATED)
      play_status=PASSED
      run_tests "$unity" "$host" PlayMode "$cell/playmode.xml" "$cell/playmode.log" || play_status=$([ -s "$cell/playmode.xml" ] && echo FAILED || echo NOT_VALIDATED)
      echo "editmode=$edit_status" >> "$cell/metadata.txt"
      echo "playmode=$play_status" >> "$cell/metadata.txt"
      if [ "$edit_status" = FAILED ] || [ "$play_status" = FAILED ]; then
        sed -i '' 's/overall_status=NOT_VALIDATED/overall_status=FAILED/' "$cell/metadata.txt"
      elif [ "$edit_status" = PASSED ] && [ "$play_status" = PASSED ]; then
        echo "batch_gates=PASSED" >> "$cell/metadata.txt"
      fi
      printf 'completed_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$cell/metadata.txt"
      record_bytes "$cell"
    done
  done
done

cat <<EOF
Compatibility attempts written to: $evidence_root
Source mode proves the current workspace package; published mode proves the pinned README install path.
Every cell remains NOT_VALIDATED until its package-specific visual, native, fixture, snippet, and Editor-only gates are reviewed and recorded.
EOF
