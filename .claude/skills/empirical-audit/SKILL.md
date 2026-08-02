---
name: empirical-audit
description: Audit a codebase claim by experiment rather than by reading. Use when an audit's findings must be PROVEN — verifying that tests actually catch regressions (mutation testing / RCR), that a guard is reachable, that a benchmark measures what it claims, or that a documented behaviour still holds. Ships a mutate-run-revert harness. NOT for ordinary code review, or for changes cheap enough to confirm by inspection.
---

# Empirical audit

Reading code tells you what it *appears* to do. This skill is for the cases where that
is not good enough and the claim has to be demonstrated.

The prompt is always some form of: *"is this thing actually doing its job?"* Line
coverage says a line executed; it does not say any test would notice if that line were
wrong. A test named `X_Throws` may pass with the throw deleted. A benchmark may measure
an empty region. Only an experiment separates these.

## The core loop

0. **Read the artifact first.** If something already failed, get its actual output —
   names, messages, counts — before theorising. A cause proposed ahead of the evidence is
   a guess, and a plausible one will absorb the whole investigation.
1. **State the hypothesis** — name the specific behaviour and the file + symbol that
   implements it.
2. **Design a perturbation** that should change an observable. One change at a time.
3. **Establish the baseline.** Green before you start, or you cannot read the result.
4. **Apply, observe, revert.** Record what actually happened, not what you predicted.
5. **Assert restoration** — the source must be byte-identical afterwards.

> **A finding is not a finding until the perturbation has been observed to change the
> outcome.** If you did not watch it change, you have a hypothesis. Write it down as one.

The single most common failure is skipping step 4 and recording the prediction as though
it were the observation. See root `AGENTS.md` §2.2.

## Mode: mutation-verification of a test suite (RCR)

The worked mode. For each test, find the one-line production edit that should make *that*
test fail, apply it, and confirm it goes red.

Admission criteria, the ADMIT/RCR comment format, and the A5 / D2 / UNFALSIFIABLE verdict
table live in each package's `Tests/AGENTS.md` §1–§2 — read them there, do not restate
them here.

```bash
python3 scripts/annotate.py spec-annotations.json   # insert comment blocks
python3 scripts/verify.py  spec-mutations.json      # mutate -> run -> revert -> report
```

Spec shapes:

```jsonc
// annotations: file -> test -> comment block (no leading indent; \n between lines)
{ "path/To/FooTest.cs": { "TestName": "// ADMIT: ...\n// RCR: ..." } }

// mutations
{ "mode": "EditMode", "filter": "<runner filter>",
  "mutations": [ { "test": "TestName", "fixture": "FooTest",
                   "file": "path/To/Foo.cs",
                   "find": "<substring, must occur EXACTLY once>",
                   "replace": "<mutated substring>" } ] }
```

## Harness contract

Every clause below exists because its absence produced a wrong answer:

- **Delete the expected output before each run**; treat a missing report as an error, not
  as an empty result. A failed run otherwise leaves the *previous* run's file in place and
  the harness reports another spec's results as yours.
- **Match on a fully-qualified identifier**, never a bare name. Duplicate method names
  across fixtures are common; without a `fixture` field a red in one silently attributes
  to the other.
- **Handle parameterized cases** whose reported name differs from the declared one
  (`Method(args)` vs `Method`).
- **Verify each `find` occurs exactly once** before running — ambiguous anchors mutate the
  wrong site.
- **Assert byte-identical restoration** of every touched file at the end.
- **Subtract the baseline's failures** so a pre-existing red is never counted as a hit.
- **Record which environment produced each result, and re-run where the observable can
  differ.** A perturbation's effect is only established in the environment you ran it in.
  For Unity that means batchmode and the Editor are separate runs: batchmode never
  instantiates the URP renderer, so anything branching on renderer/pipeline state takes a
  different path there. A suite that is green in one and red in the other is not flaky —
  it is environment-coupled, which is a finding in itself.

## Probe before you assign

For a fixture of any size, do **not** guess a perturbation per observation and verify them
one at a time. Guessing scales badly and produces confident wrong records.

Instead run a **probe pass**: pick a handful of candidate perturbations covering the
seams the fixture plausibly exercises, apply each, and record the *full set* of
observations it changes. That yields a matrix — candidate × affected observations — and
the assignment falls out of it:

- an observation changed by exactly one candidate has an isolated perturbation; take it
- a candidate that changes many observations pins none of them individually; use it only
  where nothing sharper exists, and say so
- an observation **no** candidate changes is a result, not a gap in your imagination —
  it is double-covered, redundant with a sibling, or asserting something the code does not
  own. Classify it before acting.

Worked instance: seven candidates over a 17-test fixture produced a clean 2×2 separation
for six tests, isolated one, exposed one double-guarded validation, and showed six tests
that no candidate could tell apart — the flags they claimed to vary were unreachable on
their path. Per-test guessing would have recorded six plausible, false claims.

Run the probe with a deliberately non-matching observation name so the harness reports the
whole changed set rather than short-circuiting on a match.

## Isolating a shared cause

When one perturbation changes several observations, it pins none of them individually.
Split it so each observation gets a perturbation that leaves its siblings unchanged.

A guard covering two conditions becomes two mutations: narrow it so it still fires for the
sibling's input but not for this one, then invert for the other. If no split exists — the
input trips two independent guards — that is a real result: the behaviour is
double-covered and not single-line falsifiable. Record it, do not fabricate a mutation.

## Parallelism boundary

**Analysis parallelises; execution serialises when the system under test holds a global
lock.** One Unity project = one lock (root `AGENTS.md` §2.3), so agents may read code and
draft specs concurrently, but must never invoke the runner. Verification runs centrally
afterwards. Agents that run a locked tool concurrently produce silent garbage.

Corollary worth keeping: the agent that drafts a spec should not be the one that blesses
it. Have the verifier be a different pass.

## When NOT to use this

- Changes cheap enough to confirm by reading — the experiment costs more than the answer.
- Exploratory review where you do not yet have a specific claim to test.
- Anything where a perturbation would be destructive and cannot be cleanly reverted.

## Reporting

Report observations, separating confirmed from predicted, and state the count of each.
Findings that resisted the expected remedy get classified before any action is taken, with
the evidence for the classification (root `AGENTS.md` §2.2). Never present a prediction as
a result.
