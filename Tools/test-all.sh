#!/usr/bin/env bash
# Run the suites in BOTH environments and refuse to report success unless they agree.
#
# Why this exists: batchmode and the Editor are not equivalent. Batchmode never
# instantiates the URP renderer, so anything branching on "is this renderer feature
# installed" takes the not-installed path there. Five uiservice PlayMode tests passed
# batchmode three separate times and failed 5/5 in the Editor. See root AGENTS.md 2.5
# and the A6 criterion in each package's Tests/AGENTS.md.
#
# The two halves contend for the same project lock, so they cannot overlap:
#   batchmode half -> Unity Editor must be CLOSED
#   editor half    -> Unity Editor must be OPEN (driven via unity-mcp Unity_RunCommand)
#
# Usage:
#   Tools/test-all.sh batch        # batchmode EditMode + PlayMode        (Editor closed)
#   Tools/test-all.sh editor-open  # launch the Editor and wait until the MCP bridge answers
#   Tools/test-all.sh editor       # editor-open + clear stale results + print the run snippet
#   Tools/test-all.sh editor-save  # snapshot the Editor result — run it BEFORE the batch half
#   Tools/test-all.sh compare      # compare the two recorded results
#
# Order matters: both halves write the same persistentDataPath/TestResults.xml, so the
# Editor result must be snapshotted before batchmode overwrites it.
set -euo pipefail

cd "$(dirname "$0")/.."
UNITY="${UNITY_BIN:-$HOME/.unity/bin/unity}"
OUT=".test-all"
EDITOR_RESULTS="$HOME/Library/Application Support/Game Lovers/Frameworks/TestResults.xml"
mkdir -p "$OUT"

# Identity of the code a run measured: host HEAD plus every submodule HEAD. Distinct
# start-times prove two runs happened; they do NOT prove both ran the same code, and a
# comparison straddling a code change misleads exactly as much as comparing a run with itself.
code_id() { { git rev-parse HEAD; git submodule status --recursive; } 2>/dev/null | shasum | cut -c1-12; }

# AssetImportWorker children match the same path as the interactive Editor and can outlive
# it, so "is the Editor up" must exclude them or a stale worker reads as a running Editor.
editor_pid() {
  pgrep -lf "Unity.app/Contents/MacOS/Unity" 2>/dev/null \
    | grep -v -- "-batchMode" | grep -v "AssetImportWorker" | awk 'NR==1{print $1}'
}

# Launch the Editor and block until it is actually ready to serve Unity_RunCommand.
# An MCP timeout is indistinguishable from "not running" while the Editor is still
# starting, so readiness has to be observed, not assumed.
open_editor() {
  if [ -n "$(editor_pid)" ]; then echo "editor already running (pid $(editor_pid))"; return 0; fi
  local ver app
  ver=$(sed -n 's/^m_EditorVersion: //p' ProjectSettings/ProjectVersion.txt)
  app="/Applications/Unity/Hub/Editor/$ver/Unity.app/Contents/MacOS/Unity"
  [ -x "$app" ] || { echo "ERROR: no editor at $app (project wants $ver)" >&2; exit 1; }
  echo "==> launching Unity $ver"
  nohup "$app" -projectPath "$PWD" >/dev/null 2>&1 &
  for _ in $(seq 1 90); do
    [ -n "$(editor_pid)" ] && [ -f Temp/UnityLockfile ] && break
    sleep 2
  done
  [ -n "$(editor_pid)" ] || { echo "ERROR: editor did not start" >&2; exit 1; }
  # Then wait for the import/compile pipeline to go quiet — the bridge answers only after.
  local prev="" stable=0 cur
  for _ in $(seq 1 150); do
    cur="$(ls Library/ScriptAssemblies/*.dll 2>/dev/null | wc -l)$(stat -f %m Temp/UnityLockfile 2>/dev/null)"
    if [ "$cur" = "$prev" ]; then stable=$((stable+1)); else stable=0; fi
    prev="$cur"
    [ $stable -ge 6 ] && { echo "editor quiescent (pid $(editor_pid))"; return 0; }
    sleep 3
  done
  echo "WARNING: editor still churning after ~7min; try Unity_RunCommand anyway" >&2
}

wait_for_unity() {
  # A finishing batchmode run lingers after its results file is written; launching into
  # that window aborts with a misleading "another Unity instance is running". Waits on
  # editor_pid, not a raw pgrep, so a stale AssetImportWorker does not read as an Editor
  # and block the batch half for the full timeout.
  for _ in $(seq 1 60); do
    [ -z "$(editor_pid)" ] && return 0
    sleep 2
  done
  echo "ERROR: an interactive Unity Editor is still running (pid $(editor_pid))." >&2
  echo "Close it for the batch half — the two halves share the project lock." >&2
  exit 1
}

summarise() { # <file> <label>
  python3 - "$1" "$2" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists():
    print(f"{sys.argv[2]}: MISSING ({p})"); sys.exit(1)
t = p.read_text()
m = re.search(r'<test-run[^>]*\btotal="(\d+)" passed="(\d+)" failed="(\d+)"', t)
if not m:
    print(f"{sys.argv[2]}: UNPARSEABLE"); sys.exit(1)
total, passed, failed = m.groups()
print(f"{sys.argv[2]}: total={total} passed={passed} failed={failed}")
for c in re.finditer(r'<test-case[^>]*\bfullname="([^"]+)"[^>]*\bresult="Failed"', t):
    print(f"    FAILED {c.group(1)}")
sys.exit(1 if failed != "0" else 0)
PY
}

case "${1:-batch}" in
batch)
  rc=0
  for MODE in EditMode PlayMode; do
    echo "==> batchmode $MODE"
    wait_for_unity
    # Project path "." must be explicit; the wrapper otherwise eats the next flag.
    "$UNITY" test . --mode "$MODE" --output "$OUT/batch-${MODE}.xml" || true
    code_id > "$OUT/batch-${MODE}.codeid"
    summarise "$OUT/batch-${MODE}.xml" "batch-${MODE}" || rc=1
  done
  exit $rc
  ;;

editor-open)
  open_editor
  ;;

editor)
  open_editor
  echo
  # Absence must be an error rather than a stale read, so clear it before the run.
  rm -f "$EDITOR_RESULTS"
  echo "cleared $EDITOR_RESULTS — any result read after this came from the new run"
  echo
  cat <<'SNIPPET'
Now run this through unity-mcp Unity_RunCommand (one top-level class, no nested
types, no NUnit types — the tool's rewriter breaks both):

using UnityEngine;
using UnityEditor;
using UnityEditor.TestTools.TestRunner.Api;

internal class CommandScript : IRunCommand
{
    public void Execute(ExecutionResult result)
    {
        var api = ScriptableObject.CreateInstance<TestRunnerApi>();
        api.Execute(new ExecutionSettings(new Filter { testMode = TestMode.PlayMode }));
        result.Log("Editor PlayMode run started");
    }
}

It writes to:
  ~/Library/Application Support/Game Lovers/Frameworks/TestResults.xml

Then, BEFORE closing the Editor or starting the batch half:
  Tools/test-all.sh editor-save
SNIPPET
  ;;

editor-save)
  # Snapshot the Editor half immediately. Batchmode writes the SAME persistentDataPath
  # file, so deferring this to `compare` silently yields the batch run twice and a
  # green "BOTH ENVIRONMENTS" that compared one environment with itself.
  [ -f "$EDITOR_RESULTS" ] || { echo "ERROR: no Editor results at $EDITOR_RESULTS" >&2; exit 1; }
  cp "$EDITOR_RESULTS" "$OUT/editor-PlayMode.xml"
  code_id > "$OUT/editor-PlayMode.codeid"
  summarise "$OUT/editor-PlayMode.xml" "editor-PlayMode(saved)"
  ;;

compare)
  rc=0
  summarise "$OUT/batch-PlayMode.xml" "batch-PlayMode" || rc=1
  # Deliberately NOT copying from $EDITOR_RESULTS here — see editor-save.
  summarise "$OUT/editor-PlayMode.xml" "editor-PlayMode" || rc=1
  python3 - "$OUT/batch-PlayMode.xml" "$OUT/editor-PlayMode.xml" <<'PY' || rc=1
import sys, xml.etree.ElementTree as ET, pathlib
def stamp(p):
    p = pathlib.Path(p)
    return ET.parse(p).getroot().get("start-time") if p.exists() else None
b, e = stamp(sys.argv[1]), stamp(sys.argv[2])
if b and e and b == e:
    print(f"    ERROR: both files report start-time {b} — this is ONE run compared with")
    print( "    itself, not two environments. Re-run the Editor half and `editor-save`.")
    sys.exit(1)
print(f"    distinct runs: batch={b} editor={e}")
PY
  bid=$(cat "$OUT/batch-PlayMode.codeid" 2>/dev/null || echo "?")
  eid=$(cat "$OUT/editor-PlayMode.codeid" 2>/dev/null || echo "?")
  if [ "$bid" = "?" ] || [ "$eid" = "?" ]; then
    # Fail closed: an unprovable claim must not pass. See root AGENTS.md 2.2, "a verifier's
    # own PASS is not evidence".
    echo "    ERROR: a code id is missing (batch=$bid editor=$eid), so same-code cannot be"
    echo "    proven. Re-run the half that lacks one; do not read the verdict below."
    rc=1
  elif [ "$bid" != "$eid" ]; then
    echo "    ERROR: the halves measured DIFFERENT code (batch=$bid editor=$eid)."
    echo "    Distinct start-times only prove two runs happened. Re-run the stale half."
    rc=1
  else
    echo "    same code: $bid"
  fi
  echo
  if [ $rc -eq 0 ]; then
    echo "BOTH ENVIRONMENTS GREEN"
  else
    echo "DISAGREEMENT OR FAILURE — a suite green in only one environment is"
    echo "environment-coupled, not flaky. Treat it as a finding (A6)."
  fi
  exit $rc
  ;;

*) echo "usage: $0 {batch|editor-open|editor|editor-save|compare}" >&2; exit 2 ;;
esac
