#!/usr/bin/env bash
# Serial smoke/asset verification for the bundled Mobile Services sample scenes.
# Unity owns a project-wide lock, so this script deliberately runs one editor at a time.
set -euo pipefail

cd "$(dirname "$0")/.."
PACKAGE="Packages/com.gamelovers.mobileservices"
OUT=".test-all/mobile-samples"
mkdir -p "$OUT"

SAMPLE_COUNT=$(jq '.samples | length' "$PACKAGE/package.json")
SAMPLE_DISPLAY_NAME=$(jq -r '.samples | if length == 1 then .[0].displayName else empty end' "$PACKAGE/package.json")
SAMPLE_RELATIVE_PATH=$(jq -r '.samples | if length == 1 then .[0].path else empty end' "$PACKAGE/package.json")
if [[ "$SAMPLE_COUNT" != "1" || -z "$SAMPLE_DISPLAY_NAME" || -z "$SAMPLE_RELATIVE_PATH" || "$SAMPLE_RELATIVE_PATH" == "null" ]]; then
  echo "ERROR: package.json must expose exactly one sample entry" >&2
  exit 1
fi
SAMPLE_ROOT="$PACKAGE/$SAMPLE_RELATIVE_PATH"
EDITORS=(${MOBILE_SAMPLES_EDITORS:-6000.5.7f1 6000.3.21f1 6000.0.81f1})
blocked=0
verified=0

static_check() {
  local failures=0 sample_dir sample scene sample_uss sample_ui panel_settings panel_settings_count theme theme_guid
  local -a scenes=()
  [[ -f "$SAMPLE_ROOT/GameLovers.MobileServices.Samples.asmdef" ]] || {
    echo "ERROR: missing bundled runtime asmdef" >&2
    failures=1
  }
  [[ -f "$SAMPLE_ROOT/Editor/GameLovers.MobileServices.Samples.Editor.asmdef" ]] || {
    echo "ERROR: missing bundled editor asmdef" >&2
    failures=1
  }
  [[ -f "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCatalog.cs" ]] || {
    echo "ERROR: missing bundled sample catalog" >&2
    failures=1
  }
  [[ -f "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCatalogAsset.cs" &&
     -f "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCatalog.asset" ]] || {
    echo "ERROR: missing serialized SceneAsset catalog asset/type" >&2
    failures=1
  }
  [[ -f "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCatalogVerification.cs" ]] || {
    echo "ERROR: missing catalog identity verification entry point" >&2
    failures=1
  }
  [[ -f "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCommands.cs" ]] || {
    echo "ERROR: missing Build All / Restore All commands" >&2
    failures=1
  }
  [[ -f "$SAMPLE_ROOT/Shared/MobileServicesSampleNavigation.cs" ]] || {
    echo "ERROR: missing shared sample navigation" >&2
    failures=1
  }

  while IFS= read -r scene; do
    scenes+=("$scene")
  done < <(find "$SAMPLE_ROOT" -mindepth 2 -maxdepth 2 -type f -name '*.unity' -print | sort)
  if [[ "${#scenes[@]}" != "4" ]]; then
    echo "ERROR: expected exactly four authored sample scenes from the imported bundle, found ${#scenes[@]}" >&2
    failures=1
  fi

  for scene in "${scenes[@]}"; do
    sample_dir=$(dirname "$scene")
    sample=$(basename "$sample_dir")
    rg -F -q "$sample" "$SAMPLE_ROOT/Shared/MobileServicesSamplePage.cs" || {
      echo "ERROR: bundled page catalog is missing the scene page for $sample" >&2
      failures=1
    }

    panel_settings=$(find "$SAMPLE_ROOT/$sample" -maxdepth 1 -name '* Panel Settings.asset' -print)
    panel_settings_count=$(printf '%s\n' "$panel_settings" | sed '/^$/d' | wc -l | tr -d ' ')
    if [[ "$panel_settings_count" != "1" ]]; then
      echo "ERROR: expected one PanelSettings asset for $sample, found $panel_settings_count" >&2
      failures=1
      continue
    fi
    theme="$SAMPLE_ROOT/$sample/UnityDefaultRuntimeTheme.tss"
    [[ -f "$theme" && -f "$theme.meta" ]] || {
      echo "ERROR: missing self-contained runtime theme for $sample" >&2
      failures=1
      continue
    }
    theme_guid=$(sed -n 's/^guid: //p' "$theme.meta")
    if [[ -z "$theme_guid" ]] || ! rg -F -q "guid: $theme_guid" "$panel_settings"; then
      echo "ERROR: $sample PanelSettings does not reference its runtime theme" >&2
      failures=1
    fi
    rg -F -q 'unity-theme://default' "$theme" || {
      echo "ERROR: $sample runtime theme does not import Unity default controls" >&2
      failures=1
    }

    sample_uss="$SAMPLE_ROOT/$sample/$sample.uss"
    for selector in '.sample-button:hover' '.sample-button:active' '.sample-button:focus' '.sample-button:disabled' \
      '.sample-primary-action:hover' '.sample-primary-action:active' '.sample-primary-action:focus' '.sample-primary-action:disabled'; do
      rg -F -q "$selector" "$sample_uss" || {
        echo "ERROR: $sample is missing button feedback selector $selector" >&2
        failures=1
      }
    done

    sample_ui="$SAMPLE_ROOT/$sample/${sample}UI.cs"
    rg -F -q 'RegisterCallback<ClickEvent>' "$sample_ui" || {
      echo "ERROR: $sample does not bind committed click haptics" >&2
      failures=1
    }
    rg -F -q 'HapticPreset.Selection' "$sample_ui" || {
      echo "ERROR: $sample click feedback does not use the Selection preset" >&2
      failures=1
    }
    rg -F -q 'SampleStatusFormatter.Format' "$sample_ui" || {
      echo "ERROR: $sample does not use the shared Field: Value status formatter" >&2
      failures=1
    }
    rg -F -q 'name="sample-navigation"' "$SAMPLE_ROOT/$sample/$sample.uxml" || {
      echo "ERROR: $sample does not host the shared bottom navigation" >&2
      failures=1
    }
  done

  if ! rg -F -q 'MobileServicesSampleScrollController.Attach(root.Q<ScrollView>(), root, host, _gestureController)' "$SAMPLE_ROOT/Shared/MobileServicesSampleNavigation.cs"; then
    echo "ERROR: shared sample navigation does not attach the root scroll controller" >&2
    failures=1
  fi
  if ! rg -F -q '_gestureController.PotentiallySwiped += OnPotentiallySwiped' "$SAMPLE_ROOT/Shared/MobileServicesSampleNavigation.cs"; then
    echo "ERROR: shared sample navigation is missing the touch gesture scroll fallback" >&2
    failures=1
  fi
  if ! rg -F -q '.sample-button--pressed' "$SAMPLE_ROOT/Shared/MobileServicesSampleNavigation.uss"; then
    echo "ERROR: shared sample navigation is missing deterministic pressed-state styling" >&2
    failures=1
  fi

  if rg -n '<ui:Toggle[^>]+name="enabled"' "$SAMPLE_ROOT/HapticsPalette" --glob '*.uxml'; then
    echo "ERROR: HapticsPalette must keep click haptics enabled without a toggle" >&2
    failures=1
  fi
  if rg -n ' • ' "$SAMPLE_ROOT" --glob '*UI.cs'; then
    echo "ERROR: sample status text must not use dot separators" >&2
    failures=1
  fi
  if rg -n 'UnityEngine\.(UI(\.|;)|EventSystems(\.|;))|InputSystemUIInputModule|StandaloneInputModule' \
    "$SAMPLE_ROOT" --glob '*.cs' --glob '!*/Editor/*'; then
    echo "ERROR: sample runtime references uGUI" >&2
    failures=1
  fi
  if rg -F -q '"com.unity.ugui"' "$PACKAGE/package.json"; then
    echo "ERROR: Mobile Services package must not depend on com.unity.ugui" >&2
    failures=1
  fi
  if rg -n "EditorPrefs" "$SAMPLE_ROOT" --glob '*.cs'; then
    echo "ERROR: sample build controls must not use EditorPrefs" >&2
    failures=1
  fi
  if rg -n '"[0-9a-fA-F]{32}"' "$SAMPLE_ROOT/Editor" --glob '*.cs'; then
    echo "ERROR: sample editor C# contains a hand-authored 32-character GUID literal" >&2
    failures=1
  fi
  if rg -n '"[^"]*\.unity"' "$SAMPLE_ROOT/Editor" --glob '*.cs'; then
    echo "ERROR: sample editor C# contains a hand-authored .unity path literal" >&2
    failures=1
  fi
  if rg -n "Type\\.GetType|System\\.Reflection|BindingFlags" "$SAMPLE_ROOT/Editor/Build" --glob '*.cs'; then
    echo "ERROR: sample build tooling must not use reflection" >&2
    failures=1
  fi
  if [[ -d "$PACKAGE/Editor/Build" ]]; then
    echo "ERROR: package-wide Editor/Build folder must not own sample tooling" >&2
    failures=1
  fi
  rg -F -q 'config.AndroidManifest.Vibrate = true' "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCatalog.cs" || {
    echo "ERROR: bundled sample catalog does not enable Android vibration" >&2
    failures=1
  }
  rg -F -q 'Tools/Mobile Samples Examples/Build All' "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCommands.cs" || {
    echo "ERROR: bundled sample tooling is missing Build All" >&2
    failures=1
  }
  rg -F -q 'Tools/Mobile Samples Examples/Restore All' "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCommands.cs" || {
    echo "ERROR: bundled sample tooling is missing Restore All" >&2
    failures=1
  }
  rg -F -q 'SessionState' "$SAMPLE_ROOT/Editor/Build/MobileServicesSampleBuildCommands.cs" || {
    echo "ERROR: sample restoration state is not session-scoped" >&2
    failures=1
  }
  if rg -n 'Open Build Setup|Build Sample\.\.\.' "$SAMPLE_ROOT" --glob '*.cs' --glob '*.uxml' --glob '*.uss'; then
    echo "ERROR: obsolete sample build window remains in the bundled sample tooling" >&2
    failures=1
  fi
  if [[ ! -f "$PACKAGE/Editor/Simulation/MobileNotificationSimulation.cs" ]]; then
    echo "ERROR: missing editor notification simulation broker" >&2
    failures=1
  fi
  rg -F -q 'MobileNotificationSimulation.Tick()' "$PACKAGE/Editor/Explorer/DeviceSimulatorPanel/MobileServicesDeviceSimulatorPlugin.cs" || {
    echo "ERROR: Device Simulator plugin does not tick the notification simulation bridge" >&2
    failures=1
  }
  rg -F -q 'Deliver next pending' "$PACKAGE/Editor/Explorer/DeviceSimulatorPanel/MobileServicesDeviceSimulatorPlugin.cs" || {
    echo "ERROR: Device Simulator plugin is missing explicit pending-notification delivery" >&2
    failures=1
  }
  rg -F -q 'MobileNotificationSimulation.Register' "$SAMPLE_ROOT/Editor/Simulation" --glob '*.cs' || {
    echo "ERROR: NotificationsScheduler sample does not register its simulation adapter" >&2
    failures=1
  }
  rg -F -q '"GameLovers.MobileServices.Samples"' "$SAMPLE_ROOT/Editor/GameLovers.MobileServices.Samples.Editor.asmdef" || {
    echo "ERROR: bundled editor asmdef must directly reference the bundled runtime assembly" >&2
    failures=1
  }
  rg -F -q 'editor-only' "$PACKAGE/docs/notifications.md" || {
    echo "ERROR: notification documentation does not describe the editor-only simulation bridge" >&2
    failures=1
  }
  if (( failures == 0 )); then
    echo "static sample identity: display=$SAMPLE_DISPLAY_NAME path=$SAMPLE_RELATIVE_PATH root=$SAMPLE_ROOT views=${#scenes[@]} input=InputForUI ugui=absent"
  fi

  return "$failures"
}

static_check

if [[ "${1:-quick}" == "prepare-behavior" ]]; then
  version="${2:?Usage: Tools/verify-mobile-samples.sh prepare-behavior <Unity version>}"
  unity="/Applications/Unity/Hub/Editor/$version/Unity.app/Contents/MacOS/Unity"
  [[ -x "$unity" ]] || { echo "ERROR: no editor at $unity" >&2; exit 1; }
  host="$OUT/behavior-hosts/$version"
  behavior_output="$OUT/$version-behavior"
  if [[ -e "$host" ]]; then mv "$host" "$host.stale-$(date +%Y%m%d%H%M%S)"; fi
  if [[ -e "$behavior_output" ]]; then mv "$behavior_output" "$behavior_output.stale-$(date +%Y%m%d%H%M%S)"; fi
  mkdir -p "$host/Assets/Editor" "$host/Assets/Samples" "$host/Packages" "$host/ProjectSettings" "$behavior_output"
  package_path=$(cd "$PACKAGE" && pwd)
  printf '{\n  "dependencies": {\n    "com.gamelovers.mobileservices": "file:%s"\n  }\n}\n' "$package_path" > "$host/Packages/manifest.json"
  printf 'm_EditorVersion: %s\n' "$version" > "$host/ProjectSettings/ProjectVersion.txt"
  cp ProjectSettings/ProjectSettings.asset "$host/ProjectSettings/"
  cp -R "$SAMPLE_ROOT" "$host/Assets/Samples/$(basename "$SAMPLE_RELATIVE_PATH")"
  cp Tools/Unity/MobileSamplesInputForUiVerifier.cs "$host/Assets/Editor/"
  echo "behavior-host=$host"
  echo "behavior-output=$behavior_output"
  exit 0
fi

if [[ "${1:-quick}" == "quick" ]]; then
  echo "static sample checks passed (quick mode; no Unity process started)"
  exit 0
fi

for version in "${EDITORS[@]}"; do
  unity="/Applications/Unity/Hub/Editor/$version/Unity.app/Contents/MacOS/Unity"
  if [[ ! -x "$unity" ]]; then
    echo "SKIP $version: editor not installed" >&2
    blocked=$((blocked + 1))
    continue
  fi
  artifact="$OUT/$version.log"
  lock_artifact="$OUT/$version-packages-lock.json"
  catalog_artifact="$OUT/$version-catalog.txt"
  if [[ -e "$artifact" ]]; then mv "$artifact" "$artifact.stale-$(date +%Y%m%d%H%M%S)"; fi
  if [[ -e "$lock_artifact" ]]; then mv "$lock_artifact" "$lock_artifact.stale-$(date +%Y%m%d%H%M%S)"; fi
  if [[ -e "$catalog_artifact" ]]; then mv "$catalog_artifact" "$catalog_artifact.stale-$(date +%Y%m%d%H%M%S)"; fi
  host=$(mktemp -d "${TMPDIR:-/tmp}/mobile-services-$version.XXXXXX")
  mkdir -p "$host/Assets" "$host/Packages" "$host/ProjectSettings"
  package_path=$(cd "$PACKAGE" && pwd)
  printf '{\n  "dependencies": {\n    "com.gamelovers.mobileservices": "file:%s"\n  }\n}\n' "$package_path" > "$host/Packages/manifest.json"
  printf 'm_EditorVersion: %s\n' "$version" > "$host/ProjectSettings/ProjectVersion.txt"
  mkdir -p "$host/Assets/Samples"
  cp -R "$SAMPLE_ROOT" "$host/Assets/Samples/$(basename "$SAMPLE_RELATIVE_PATH")"
  started=$(date +%s)
  echo "==> importing and compiling samples with Unity $version"
  run_rc=0
  MOBILE_SAMPLES_CATALOG_ARTIFACT="$PWD/$catalog_artifact" \
    "$unity" -batchmode -nographics -quit -projectPath "$host" \
    -logFile "$PWD/$artifact" \
    -executeMethod GameLovers.MobileServices.Samples.Editor.Build.MobileServicesSampleBuildCatalogVerification.WriteArtifact || run_rc=$?
  lock_rc=0
  if [[ ! -s "$host/Packages/packages-lock.json" ]]; then
    echo "BLOCKED $version: Unity did not create a resolved package lock" >&2
    lock_rc=1
  else
    cp "$host/Packages/packages-lock.json" "$lock_artifact"
    if rg -F -q '"com.unity.ugui"' "$lock_artifact"; then
      echo "BLOCKED $version: clean host resolved com.unity.ugui" >&2
      lock_rc=1
    fi
  fi
  rm -rf "$host"
  if [[ ! -s "$artifact" ]]; then
    echo "BLOCKED $version: Unity did not create an import/compile log (exit=$run_rc); inspect $artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  modified=$(stat -f %m "$artifact")
  if (( modified < started )); then
    echo "BLOCKED $version: import/compile log predates this run: $artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  if rg -n 'error CS[0-9]+|Scripts have compiler errors|Script Compilation Error|Assembly.*compile error' "$artifact"; then
    echo "BLOCKED $version: the imported sample bundle did not compile; inspect $artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  if (( run_rc != 0 )); then
    echo "BLOCKED $version: Unity exited $run_rc without a recognised compiler error; inspect $artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  if (( lock_rc != 0 )); then
    blocked=$((blocked + 1))
    continue
  fi
  if [[ ! -s "$catalog_artifact" ]]; then
    echo "BLOCKED $version: Unity did not create the non-empty catalog identity artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  catalog_modified=$(stat -f %m "$catalog_artifact")
  if (( catalog_modified < started )); then
    echo "BLOCKED $version: catalog identity artifact predates this run: $catalog_artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  if ! awk -F '\t' '
    NR == 1 { if ($0 != "mobile-services-sample-catalog-v1") exit 10; next }
    NF != 3 || $1 == "" || $2 == "" || $3 !~ /^[0-9a-fA-F]{32}$/ { exit 11 }
    { pages[$1]++; paths[$2]++; guids[$3]++; count++ }
    END {
      if (count != 4) exit 12
      for (key in pages) if (pages[key] != 1) exit 13
      for (key in paths) if (paths[key] != 1) exit 14
      for (key in guids) if (guids[key] != 1) exit 15
    }
  ' "$catalog_artifact"; then
    echo "BLOCKED $version: catalog identity artifact is malformed or does not contain four unique page/path/GUID rows: $catalog_artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  lock_modified=$(stat -f %m "$lock_artifact")
  if (( lock_modified < started )); then
    echo "BLOCKED $version: resolved package lock predates this run: $lock_artifact" >&2
    blocked=$((blocked + 1))
    continue
  fi
  echo "$version: imported-sample=compiled catalog=4-unique-page-path-guid-rows ugui=absent log=$artifact lock=$lock_artifact catalog-artifact=$catalog_artifact"
  verified=$((verified + 1))
done

if (( blocked > 0 )); then
  echo "verification summary: passed-editors=$verified blocked-editors=$blocked" >&2
  exit 1
fi

if (( verified == 0 )); then
  echo "verification summary: no supported Unity editor was available" >&2
  exit 1
fi

echo "verification summary: imported-sample-compiles=$verified"
