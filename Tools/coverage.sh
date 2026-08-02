#!/usr/bin/env bash
# Full instrumented coverage run (EditMode + PlayMode) merged into one report.
#
# Filter notes — these are load-bearing, do not "simplify" them:
#   -*Tests*   test assemblies score themselves at 0% and only inflate the
#              denominator. `-*Tests` alone does NOT work: assembly names like
#              GameLovers.UiService.Tests.PlayMode do not END in "Tests", so the
#              glob must be contains-style. Getting this wrong understated the
#              whole-project figure by ~7 points (33.8% vs 41.0%).
#   -*Samples* sample assemblies are demo code, not shipped API surface.
#
# Metric caveats baked into Unity's producer, NOT fixable in the report:
#   nPathComplexity is emitted as 0 for every method — the Code Coverage package
#   does not compute it. generateAdditionalMetrics enables cyclomatic complexity
#   and CRAP only.
#   branchCoverage is likewise always 0 (sequence-point coverage only), which
#   makes CRAP systematically OPTIMISTIC: it divides by sequence coverage, so a
#   method with untaken branches scores better than it deserves.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$PWD/CodeCoverage"
rm -rf "$OUT" && mkdir -p "$OUT"
OPTS="generateAdditionalMetrics;generateHtmlReport;assemblyFilters:+GameLovers.*,-*Tests*,-*Samples*"
for MODE in EditMode PlayMode; do
  echo "=== $MODE (instrumented) ==="
  ~/.unity/bin/unity test . --mode "$MODE" --output "/tmp/cov-${MODE}.xml" -- \
    -enableCodeCoverage -debugCodeOptimization \
    -coverageResultsPath "$OUT" -coverageOptions "$OPTS"
done
echo "report: file://$OUT/Report/index.html"
