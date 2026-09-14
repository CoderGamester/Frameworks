#!/usr/bin/env bash

set -euo pipefail

ProjectRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ProjectRoot
readonly Tool="$ProjectRoot/Tools/agent-roster.py"
Scratch="$(mktemp -d "${TMPDIR:-/tmp}/agent-roster.XXXXXX")"
readonly Scratch
readonly State="$Scratch/state"
readonly Repo="$Scratch/repo"
trap 'rm -rf "$Scratch"' EXIT
Passed=0
Failed=0

pass() {
  printf 'PASS  %s\n' "$1"
  Passed=$((Passed + 1))
}

fail() {
  printf 'FAIL  %s\n' "$1"
  Failed=$((Failed + 1))
}

expect_eq() {
  local description="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$description"
  else
    fail "$description (expected=$expected actual=$actual)"
  fi
}

expect_contains() {
  local description="$1" actual="$2" expected="$3"
  if [[ "$actual" == *"$expected"* ]]; then
    pass "$description"
  else
    fail "$description (missing=$expected actual=$actual)"
  fi
}

run_event() {
  local event="$1" host="$2" payload="$3"
  printf '%s' "$payload" | "$Tool" --state-dir "$State" --repo-root "$Repo" --host "$host" --strict "$event"
}

classify() {
  "$Tool" --classify-entry "$1"
}

git init -q -b main "$Repo"
git -C "$Repo" config user.name "Agent Roster Fixture"
git -C "$Repo" config user.email "agent-roster@example.invalid"
git -C "$Repo" config commit.gpgsign false
printf 'fixture\n' >"$Repo/tracked.txt"
git -C "$Repo" add -- tracked.txt
git -C "$Repo" commit -q -m "fixture"

expect_eq "missing entries classify separately" "missing" "$(classify "$State/missing.json")"

mkdir -p "$State"
printf 'not json\n' >"$State/broken.json"
expect_eq "invalid JSON is rejected" "invalid-json" "$(classify "$State/broken.json")"

printf '{"host":"claude"}\n' >"$State/schema.json"
expect_eq "incomplete entries are rejected" "invalid-schema" "$(classify "$State/schema.json")"

now="$(date -u '+%Y-%m-%dT%H:%M:%S+00:00')"
cat >"$State/live.json" <<EOF
{"key":"claude-live","host":"claude","conversation_id":"live","root":"$Repo","branch":"main","head":"abc","dirty_paths":[],"intent":"","joined_at":"$now","last_seen":"$now"}
EOF
expect_eq "fresh entries are live" "live" "$(classify "$State/live.json")"

cat >"$State/stale.json" <<EOF
{"key":"claude-stale","host":"claude","conversation_id":"stale","root":"$Repo","branch":"main","head":"abc","dirty_paths":[],"intent":"","joined_at":"2020-01-01T00:00:00+00:00","last_seen":"2020-01-01T00:00:00+00:00"}
EOF
expect_eq "expired entries are stale" "stale" "$(classify "$State/stale.json")"

before_hash="$(shasum -a 256 "$State/live.json" | awk '{print $1}')"
classify "$State/live.json" >/dev/null
after_hash="$(shasum -a 256 "$State/live.json" | awk '{print $1}')"
expect_eq "classification is read-only" "$before_hash" "$after_hash"

rm -rf "$State"
output="$(run_event join claude '{"session_id":"s1"}')"
expect_contains "Claude join emits SessionStart context" "$output" '"hookEventName": "SessionStart"'
expect_contains "a lone session names its roster key" "$output" 'claude-s1'
if [[ -f "$State/claude-s1.json" ]]; then
  pass "join creates one session entry"
else
  fail "join did not create its session entry"
fi
state_mode="$(python3 -c 'import stat,sys; print(format(stat.S_IMODE(__import__("os").lstat(sys.argv[1]).st_mode), "o"))' "$State")"
expect_eq "the state directory is private" "700" "$state_mode"

joined_at="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["joined_at"])' "$State/claude-s1.json")"
sleep 1
run_event join claude '{"session_id":"s1"}' >/dev/null
rejoined_at="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["joined_at"])' "$State/claude-s1.json")"
entry_count="$(find "$State" -name '*.json' -type f | wc -l | tr -d ' ')"
expect_eq "rejoin preserves the original join time" "$joined_at" "$rejoined_at"
expect_eq "rejoin updates instead of duplicating" "1" "$entry_count"

run_event join claude '{"session_id":"child","agent_id":"agent-1"}' >/dev/null
if [[ ! -e "$State/claude-child.json" ]]; then
  pass "subagent SessionStart does not register"
else
  fail "subagent SessionStart created a peer entry"
fi

parent_file_identity="$(python3 -c 'import os,sys; value=os.stat(sys.argv[1]); print(f"{value.st_ino}:{value.st_mtime_ns}")' "$State/claude-s1.json")"
run_event beat claude '{"session_id":"s1","agent_id":"agent-1"}' >/dev/null
run_event leave claude '{"session_id":"s1","agent_id":"agent-1"}' >/dev/null
expect_eq "subagent heartbeat cannot refresh its parent" "$parent_file_identity" "$(python3 -c 'import os,sys; value=os.stat(sys.argv[1]); print(f"{value.st_ino}:{value.st_mtime_ns}")' "$State/claude-s1.json")"
if [[ -e "$State/claude-s1.json" ]]; then
  pass "subagent SessionEnd cannot remove its parent"
else
  fail "subagent SessionEnd removed its parent"
fi

mkdir -p "$Repo/nested/path"
nested_output="$(
  printf '%s' "{\"session_id\":\"nested\",\"cwd\":\"$Repo/nested/path\"}" \
    | "$Tool" --state-dir "$State" --host claude --strict join
)"
expect_contains "nested launches still receive roster context" "$nested_output" 'Agent roster snapshot'
nested_root="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' "$State/claude-nested.json")"
canonical_repo="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$Repo")"
expect_eq "nested launch paths canonicalize to the Git root" "$canonical_repo" "$nested_root"
run_event leave claude '{"session_id":"nested"}' >/dev/null

printf 'new work\n' >"$Repo/new.txt"
index_mtime_before="$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)' "$Repo/.git/index")"
roster_json="$("$Tool" --state-dir "$State" --repo-root "$Repo" roster --json)"
index_mtime_after="$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)' "$Repo/.git/index")"
expect_contains "roster derives post-join dirty paths from Git" "$roster_json" '"new.txt"'
expect_contains "roster labels changed paths without claiming authorship" "$roster_json" '"checkout_paths_changed_since_join"'
if [[ "$roster_json" != *'post_join_dirty_paths'* ]]; then
  pass "roster does not expose the misleading attribution field"
else
  fail "roster still exposes post_join_dirty_paths"
fi
expect_eq "read-only roster queries do not refresh the Git index" "$index_mtime_before" "$index_mtime_after"

git -C "$Repo" mv -- tracked.txt "renamed file.txt"
roster_json="$("$Tool" --state-dir "$State" --repo-root "$Repo" roster --json)"
expect_contains "rename evidence includes the source path" "$roster_json" '"tracked.txt"'
expect_contains "rename evidence includes the destination path" "$roster_json" '"renamed file.txt"'

intent_output="$("$Tool" --state-dir "$State" --repo-root "$Repo" --strict intent 'editing setup tooling')"
expect_contains "intent resolves the unique session in this checkout" "$intent_output" 'Updated intent for claude-s1'
expect_contains "intent is visible in roster output" "$("$Tool" --state-dir "$State" roster)" 'editing setup tooling'
if python3 - "$Tool" "$State" "$Repo" <<'PY'
import subprocess
import sys

process = subprocess.Popen(
    [
        sys.argv[1],
        "--state-dir",
        sys.argv[2],
        "--repo-root",
        sys.argv[3],
        "--strict",
        "intent",
        "nonblocking stdin",
        "--key",
        "claude-s1",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    process.wait(timeout=2)
except subprocess.TimeoutExpired:
    process.kill()
    process.wait()
    raise SystemExit(1)
raise SystemExit(process.returncode)
PY
then
  pass "interactive intent does not wait for stdin"
else
  fail "interactive intent blocked while stdin remained open"
fi

cursor_output="$(run_event join cursor '{"conversation_id":"c1","cursor_version":"2026.3"}')"
expect_contains "Cursor join emits Cursor context shape" "$cursor_output" '"additional_context"'
expect_contains "a second session sees its peer" "$cursor_output" 'claude-s1'
# The snapshot is injected before any skill trigger matches, so it carries the coordination route.
expect_contains "the peer snapshot names the coordination skill" "$cursor_output" 'multi-agent-session'

cursor_output="$(
  printf '%s' '{"conversation_id":"c2","cursor_version":"2026.3"}' \
    | "$Tool" --state-dir "$State" --repo-root "$Repo" --strict join --host claude --future-flag x
)"
expect_contains "host-appended and future flags are ignored" "$cursor_output" '"additional_context"'
if [[ -e "$State/cursor-c2.json" ]]; then
  pass "payload host evidence outranks ignored appended flags"
else
  fail "appended flags prevented Cursor registration"
fi

codex_output="$(run_event join codex '{"session_id":"x1"}')"
expect_contains "Codex join emits plain context" "$codex_output" 'Agent roster snapshot'
if [[ "$codex_output" != \{* ]]; then
  pass "Codex SessionStart output is not a JSON decision"
else
  fail "Codex SessionStart output unexpectedly used a decision document"
fi

old_seen="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["last_seen"])' "$State/codex-x1.json")"
sleep 1
run_event beat codex '{"session_id":"x1"}' >/dev/null
new_seen="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["last_seen"])' "$State/codex-x1.json")"
if [[ "$new_seen" > "$old_seen" ]]; then
  pass "beat refreshes an existing session"
else
  fail "beat did not advance last_seen"
fi
run_event leave codex '{"session_id":"x1"}' >/dev/null
if [[ ! -e "$State/codex-x1.json" ]]; then
  pass "unmarked Codex SessionEnd removes its Codex entry"
else
  fail "unmarked Codex SessionEnd left its entry"
fi

printf 'broken\n' >"$State/corrupt.json"
roster_json="$("$Tool" --state-dir "$State" roster --json)"
if [[ "$roster_json" != *'corrupt'* ]]; then
  pass "corrupt entries are skipped from roster reads"
else
  fail "corrupt entry leaked into roster output"
fi

run_event beat claude '{"session_id":"s1"}' >/dev/null
if [[ ! -e "$State/corrupt.json" ]]; then
  pass "mutating operations reap corrupt entries"
else
  fail "mutating operation left a corrupt entry"
fi

cat >"$State/expired.json" <<EOF
{"key":"claude-expired","host":"claude","conversation_id":"expired","root":"$Repo","branch":"main","head":"abc","dirty_paths":[],"intent":"","joined_at":"2020-01-01T00:00:00+00:00","last_seen":"2020-01-01T00:00:00+00:00"}
EOF
run_event beat claude '{"session_id":"s1"}' >/dev/null
if [[ ! -e "$State/expired.json" ]]; then
  pass "mutating operations reap stale entries"
else
  fail "mutating operation left a stale entry"
fi

mkdir "$State/.mutation.lock"
python3 -c 'import os,sys,time; stamp=time.time()-10; os.utime(sys.argv[1], (stamp, stamp))' "$State/.mutation.lock"
run_event beat claude '{"session_id":"s1"}' >/dev/null
if [[ ! -e "$State/.mutation.lock" ]]; then
  pass "a crash before PID publication is reaped after its grace period"
else
  fail "a PID-less abandoned lock blocked roster progress"
fi

mkdir "$State/.mutation.lock"
printf '99999999\n' >"$State/.mutation.lock/pid"
run_event beat claude '{"session_id":"s1"}' >/dev/null
if [[ ! -e "$State/.mutation.lock" ]]; then
  pass "a dead mutation-lock owner is reaped"
else
  fail "a dead mutation lock blocked roster progress"
fi

run_event leave cursor '{"conversation_id":"c1","cursor_version":"2026.3"}' >/dev/null
if [[ ! -e "$State/cursor-c1.json" ]]; then
  pass "leave removes only its session entry"
else
  fail "leave did not remove its session entry"
fi
if [[ -e "$State/claude-s1.json" ]]; then
  pass "leave preserves peer entries"
else
  fail "leave removed a peer entry"
fi

readonly HostileTarget="$Scratch/hostile-target"
readonly HostileState="$Scratch/hostile-state"
mkdir "$HostileTarget"
ln -s "$HostileTarget" "$HostileState"
if printf '%s' '{"session_id":"hostile"}' | "$Tool" --state-dir "$HostileState" --strict join >/dev/null 2>&1; then
  fail "strict mode accepted a symlinked state directory"
else
  pass "symlinked state directories are rejected"
fi
if [[ -z "$(find "$HostileTarget" -mindepth 1 -print -quit)" ]]; then
  pass "a hostile state symlink cannot redirect roster writes"
else
  fail "roster wrote through a hostile state symlink"
fi

readonly InsecureState="$Scratch/insecure-state"
mkdir "$InsecureState"
chmod 0755 "$InsecureState"
if printf '%s' '{"session_id":"insecure"}' | "$Tool" --state-dir "$InsecureState" --strict join >/dev/null 2>&1; then
  fail "strict mode accepted a broadly readable state directory"
else
  pass "broad state-directory permissions are rejected"
fi
if python3 - "$Tool" "$State" <<'PY'
import importlib.util
import os
import sys
from unittest import mock

spec = importlib.util.spec_from_file_location("agent_roster", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with mock.patch.object(module.os, "geteuid", return_value=os.lstat(sys.argv[2]).st_uid + 1):
    try:
        module.prepare_state_dir(module.Path(sys.argv[2]), create=False)
    except PermissionError:
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  pass "state directories owned by another user are rejected"
else
  fail "wrong-owner state protection did not reject the directory"
fi

readonly ConcurrentState="$Scratch/concurrent-state"
declare -a ConcurrentPids=()
printf '%s' '{"conversation_id":"parallel-a","cursor_version":"2026.3"}' \
  | "$Tool" --state-dir "$ConcurrentState" --repo-root "$Repo" --host cursor --strict join >"$Scratch/parallel-a.out" &
ConcurrentPids+=("$!")
printf '%s' '{"session_id":"parallel-b"}' \
  | "$Tool" --state-dir "$ConcurrentState" --repo-root "$Repo" --host claude --strict join >"$Scratch/parallel-b.out" &
ConcurrentPids+=("$!")
printf '%s' '{"session_id":"parallel-c"}' \
  | "$Tool" --state-dir "$ConcurrentState" --repo-root "$Repo" --host codex --strict join >"$Scratch/parallel-c.out" &
ConcurrentPids+=("$!")
printf '%s' '{"conversation_id":"parallel-d","cursor_version":"2026.3"}' \
  | "$Tool" --state-dir "$ConcurrentState" --repo-root "$Repo" --host cursor --strict join >"$Scratch/parallel-d.out" &
ConcurrentPids+=("$!")
printf '%s' '{"conversation_id":"parallel-child","cursor_version":"2026.3","agent_id":"child-1"}' \
  | "$Tool" --state-dir "$ConcurrentState" --repo-root "$Repo" --host cursor --strict join >"$Scratch/parallel-child.out" &
ConcurrentPids+=("$!")

concurrent_ok=1
for pid in "${ConcurrentPids[@]}"; do
  wait "$pid" || concurrent_ok=0
done
if [[ "$concurrent_ok" == "1" ]]; then
  pass "five concurrent lifecycle calls complete without lock failure"
else
  fail "one or more concurrent lifecycle calls failed"
fi
shopt -s nullglob
concurrent_entries=("$ConcurrentState"/*.json)
shopt -u nullglob
expect_eq "four concurrent parents register exactly once" "4" "${#concurrent_entries[@]}"
if [[ ! -e "$ConcurrentState/cursor-parallel-child.json" ]]; then
  pass "the concurrent child remains absent from the peer roster"
else
  fail "the concurrent child registered as a peer"
fi

if printf 'not json' | "$Tool" --state-dir "$State" --strict join >/dev/null 2>&1; then
  fail "strict mode rejects malformed hook payloads"
else
  pass "strict mode rejects malformed hook payloads"
fi

if printf 'not json' | "$Tool" --state-dir "$State" join >/dev/null 2>&1; then
  pass "ordinary hook failures fail open"
else
  fail "ordinary hook failure blocked the host"
fi

printf '\n%s passed, %s failed\n' "$Passed" "$Failed"
[[ "$Failed" == "0" ]]
