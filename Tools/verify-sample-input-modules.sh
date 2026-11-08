#!/usr/bin/env bash
# A Samples~ script that adds InputSystemUIInputModule programmatically must call
# AssignDefaultActions() in the same file. Without it the module has no actions: every button in the
# sample looks live, receives nothing, and emits no error, so the failure survives a green compile,
# a green test run, and a screenshot. Prose already says so in unity-package-sample-builder
# references/pitfalls.md; this is the check that fails in the commit rather than in a bug report.
#
#   bash Tools/verify-sample-input-modules.sh [--self-test]
set -euo pipefail

cd "$(dirname "$0")/.."

# Host grep and BSD userland only: this repository has no ripgrep requirement outside one script.
check_samples() { # <root>... ; prints offenders, returns their count
  local file offenders=0 scanned=0 roots=$#
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    scanned=$((scanned + 1))
    if ! grep -q -F 'AssignDefaultActions' "$file"; then
      echo "ERROR: $file adds InputSystemUIInputModule without AssignDefaultActions()" >&2
      offenders=$((offenders + 1))
    fi
  done <<EOF
$(grep -r -l -E 'AddComponent<[A-Za-z.]*InputSystemUIInputModule>' "$@" --include='*.cs' 2>/dev/null || true)
EOF
  echo "sample input modules: roots=$roots adders=$scanned offenders=$offenders"
  return "$offenders"
}

self_test() {
  local scratch status=0
  scratch="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/sample-input-selftest.XXXXXX")" && pwd)"
  trap 'rm -rf "$scratch"' RETURN
  mkdir -p "$scratch/Packages/p/Samples~/S" "$scratch/Packages/p/Runtime"
  printf 'go.AddComponent<InputSystemUIInputModule>();\n' > "$scratch/Packages/p/Samples~/S/Bad.cs"
  printf 'go.AddComponent<InputSystemUIInputModule>().AssignDefaultActions();\n' > "$scratch/Packages/p/Samples~/S/Good.cs"
  # Runtime code is outside the rule: only a sample's buttons are the thing this protects.
  printf 'go.AddComponent<InputSystemUIInputModule>();\n' > "$scratch/Packages/p/Runtime/Prod.cs"

  local out
  out="$(check_samples "$scratch/Packages"/*/Samples~ 2>&1)" && status=0 || status=$?
  case "$out" in
    *"Bad.cs adds InputSystemUIInputModule without"*) ;;
    *) echo "SELF-TEST FAILED: an offender was not reported" >&2; echo "$out" >&2; return 1 ;;
  esac
  case "$out" in
    *"Prod.cs"*) echo "SELF-TEST FAILED: Runtime code was scanned" >&2; return 1 ;;
  esac
  [ "$status" = "1" ] || { echo "SELF-TEST FAILED: expected exactly one offender, got status $status" >&2; return 1; }

  printf 'go.AddComponent<InputSystemUIInputModule>().AssignDefaultActions();\n' > "$scratch/Packages/p/Samples~/S/Bad.cs"
  if ! check_samples "$scratch/Packages"/*/Samples~ >/dev/null 2>&1; then
    echo "SELF-TEST FAILED: a compliant sample tree was rejected" >&2
    return 1
  fi
  echo "SELF-TEST PASSED: a sample module without default actions is rejected, a compliant one is not"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit $?
fi

check_samples Packages/*/Samples~
