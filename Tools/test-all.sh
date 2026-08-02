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
#   Tools/test-all.sh batch     # batchmode EditMode + PlayMode        (Editor closed)
#   Tools/test-all.sh editor    # print the snippet for the Editor half (Editor open)
#   Tools/test-all.sh compare   # compare the two recorded results
set -euo pipefail

cd "$(dirname "$0")/.."
UNITY="${UNITY_BIN:-$HOME/.unity/bin/unity}"
OUT=".test-all"
EDITOR_RESULTS="$HOME/Library/Application Support/Game Lovers/Frameworks/TestResults.xml"
mkdir -p "$OUT"

wait_for_unity() {
  # A finishing batchmode run lingers after its results file is written; launching into
  # that window aborts with a misleading "another Unity instance is running".
  for _ in $(seq 1 60); do
    pgrep -f "Unity.app/Contents/MacOS/Unity" >/dev/null || return 0
    sleep 2
  done
  echo "ERROR: a Unity process is still running. Close the Editor for the batch half." >&2
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
    summarise "$OUT/batch-${MODE}.xml" "batch-${MODE}" || rc=1
  done
  exit $rc
  ;;

editor)
  cat <<'SNIPPET'
Open the Unity Editor, then run this through unity-mcp Unity_RunCommand:

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
Then: Tools/test-all.sh compare
SNIPPET
  ;;

compare)
  rc=0
  summarise "$OUT/batch-PlayMode.xml" "batch-PlayMode" || rc=1
  cp "$EDITOR_RESULTS" "$OUT/editor-PlayMode.xml" 2>/dev/null || true
  summarise "$OUT/editor-PlayMode.xml" "editor-PlayMode" || rc=1
  echo
  if [ $rc -eq 0 ]; then
    echo "BOTH ENVIRONMENTS GREEN"
  else
    echo "DISAGREEMENT OR FAILURE — a suite green in only one environment is"
    echo "environment-coupled, not flaky. Treat it as a finding (A6)."
  fi
  exit $rc
  ;;

*) echo "usage: $0 {batch|editor|compare}" >&2; exit 2 ;;
esac
