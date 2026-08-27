---
name: code-standards-audit
description: Audit either the whole repository or the exact changed-script set against mechanical code-style, XML-documentation, naming, member-order, assembly-boundary, and shell-tool rules. Use Tools/style-audit.py only after validating its polarity and attribution. Use when asked to audit, enforce, or fix coding standards/doc-comment compliance, to normalize all changed scripts including untracked tests/samples/tools, or when a standards rule looks wrong. NOT for README/AGENTS prose (use package-docs-audit) or test coverage.
---

# Code standards audit

Repository-wide or change-scoped enforcement of the mechanical rules in root `AGENTS.md` §6.6 —
XML documentation, enum-value comments, member ordering, and adjacent script conventions.
`Tools/style-audit.py` is the engine for its supported rules; this skill is the procedure around it.

The engine already exists and already passes. Most runs are therefore small: measure, act on a
handful of findings, re-verify. The long phases below matter when the count comes back large.

> **A finding count is worthless until the tool that produced it has been validated and the rule
> it enforces has been triaged.** The first full run of this audit opened at 912 findings.
> Rewriting the rule took it to 551 before any code changed, and a further slice of the remainder
> turned out to be defects in the checker rather than real findings. Acting on the raw 912 would
> have deleted correct documentation.

---

## Phase 0 — Measure

Choose scope first:

- **Repository audit:** use the existing whole-corpus commands below.
- **Changed-script audit:** record the exact union of tracked changed and untracked `*.cs` and `*.sh` files before editing. Never substitute the current diff after fixes for the original authorized scope.

For a changed-script audit, derive and retain an inventory such as `.test-all/changed-scripts.txt`. Include submodule changes from inside each affected package; the parent repository cannot enumerate files within a submodule. Exclude deleted files from style remediation but retain them for documentation stale-symbol searches.

```bash
python3 Tools/style-audit.py                    # gate; nonzero exit on violations
python3 Tools/style-audit.py --list H G          # every finding for specific rules
python3 Tools/style-audit.py --json out.json     # machine-readable
python3 Tools/style-audit.py --advisory          # member-ordering report (NOT gated, noisy)
```

Never estimate a number that will be acted on (§2.2). For a repository audit, a validated PASS ends
the mechanical gate. For a changed-script audit, continue with the exempt-area and shell checks
below even when the global gate passes.

`Tools/style-audit.py` gates Runtime and Editor XML rules and intentionally exempts `Tests/` and `Samples~/`. A changed-script request still requires direct checks across those exempt files for private naming, member order, closure renames, comments, namespaces, assembly boundaries, and test conventions. A global style PASS does not settle that scope.

Summary layout is the exception to the XML exemption: rule L applies in Runtime, Editor, Tests, Samples, and imported Assets. A single sentence may span several physical lines; use the inline form only when the complete indented line fits within 120 columns, with tabs expanded to four columns. Once block form is used, wrapping remains a readability judgment rather than a mechanical width gate because XML references can be indivisible.

For changed shell tools, run `bash -n` and ShellCheck when installed. Treat verification scripts and Unity verifier sources as production-quality tooling: they must follow project style, compile without avoidable warnings on every supported editor, and print the identity and non-empty size of artifacts they validate.

`Tests/` and `Samples~/` are exempt by design and counted for visibility only; steer by the
`gated` column.

---

## Phase 1 — Validate the checker BEFORE trusting a count

Skip this only when the count is small enough to verify each finding by eye. Three cheap checks:

**1. Reconcile totals against an independent method.** Grep is the usual second opinion, and the
reconciliation must be exact or explained:

```bash
grep -rhE '\binterface\s+[A-Za-z_]' --include='*.cs' Packages | grep -vE '^\s*(///|//)' | wc -l
```

Recorded: interfaces reconciled 127/127 exactly; enums came back 34 vs 27 and the 7-item gap was
fully accounted for (log strings, a codegen string, a tooltip). An *unexplained* gap means the
parser is wrong, not the corpus.

**2. Sample findings against real source.** Read the actual declaration at a random handful of
file:line pairs per rule. This is what caught most of the defects below — a name like
`GameObjectPool.true` or `ValidationResult.?` in the output is a parser bug announcing itself.

**3. Polarity-test both directions:**

```bash
python3 .agents/skills/code-standards-audit/scripts/polarity-check.py
```

False negatives are invisible and false positives cause destructive edits, so the fixture asserts
must-flag *and* must-not-flag cases. Extend it whenever a new bug class is found.

### Bug classes this checker has actually had

Nine defects, five of them after it was committed and being trusted. Expect these shapes in any
C# analyser:

| Symptom in output | Root cause |
|---|---|
| Every method reported as a property | Bracket-depth branch shadowed the token test, so a search for `(` could never match |
| Expression-bodied properties counted as fields | `=>` index taken against the unstripped head, overshooting the stripped body |
| Unnamed `Type.?` private field carrying a property's doc | `public List<T> P { get; } = new();` flushes twice; the initializer tail inherits the doc lines |
| Members of a `private` nested type demanded docs | Declared instead of **effective** accessibility |
| Members of an `internal` interface judged public API | Interface members carry no modifier and default to `public` |
| Explicit interface impls (`void IFoo.Bar()`) reported private | No access modifier is legal there by language rule |
| Documented member reported undocumented | Doc walk-back stopped at a `// ReSharper disable` line — a `//` comment does **not** detach XML docs |
| `internal` after a Unity callback flagged as misordered | §6.6 gives Unity messages their own earlier ordering slot |
| `internal` after a `[DllImport] extern` flagged | P/Invoke declarations sit with the interop surface, not the private block |

The two worth internalising: the phantom-field one would have **deleted legitimate property
documentation**, and the effective-accessibility one was about to **generate summaries on
effectively-private members** — the exact inverse of the rule being enforced.

---

## Phase 2 — Triage: rule defect or code drift?

Do this before writing anything. Per §2.2, when an audit mass-fires, suspect the rule first.

| Signal | Verdict |
|---|---|
| The best-documented file in the repo is the top offender | **Rule defect.** Almost conclusive. |
| Two rules cannot both be satisfied | **Rule defect.** One must yield; decide which explicitly. |
| A rule fires on a whole category (every interface property) | **Rule defect** — the rule was written without checking the corpus. |
| Scattered, no pattern, each defensible in isolation | **Code drift.** Remediate. |

Recorded instances of the first three: `IUiService.cs` was simultaneously the most carefully
documented file and the largest source of `<param>` violations, because the ban was unscoped;
§6.6 said methods *always* use the block form while §2.7 said internal types get *one-sentence*
summaries; and "properties collapse to a single line" fired on essentially every interface
property in two packages.

**Fix the rule first, in `AGENTS.md`, then re-measure.** Amending a rule is one edit; the
alternative is hundreds. Present each conflict to the user with the count attached — the
resolution is theirs, not yours.

⚠️ Editing §6.6's `### Code comments` subsection has a hidden cost: all six
`Packages/*/Tests/AGENTS.md` quote it **verbatim** and line 7 of each mandates that any change be
applied to all six in the same session, one commit per submodule. Confine edits to
`### XML documentation rules` and that mandate never fires. Verify with a byte comparison:

```bash
extract() { awk '/^### Code comments$/{f=1} /^### XML documentation rules$/{f=0} f'; }
diff <(git show HEAD:AGENTS.md | extract) <(extract < AGENTS.md) && echo IDENTICAL
```

Print the byte count too — a diff of two empty extracts passes vacuously (§2.2).

---

## Phase 3 — Remediate mechanical first

Order matters: mechanical edits are script-verifiable, prose is not. Doing them together makes
the diff unreviewable.

**Mechanical** — deletions (docs on private members, on constructors), enum `///` → inline `//`,
banned-tag removal, member moves, and `/// <inheritdoc />` on overrides.

**One precondition on `<inheritdoc />`:** it must point at a base that actually carries a
`<summary>`. Aimed at an undocumented base it yields empty IntelliSense, no compiler error, and
reads as "documented" to any checker. So classify each override first:

- external base (Unity, `System.Object`) → safe, the framework ships docs
- own base, documented → safe
- own base, undocumented → **defer**; document the base in Phase 4, which unblocks it

That deferral is high-leverage. Recorded: 17 of 30 deferred overrides all inherited from one
file (`uiservice/Editor/UiConfigsEditorBase.cs`); documenting its 6 extension points unblocked
all 17 at once.

**When deleting a doc from a private member**, hold it to §6.6's bar — a comment there is a last
resort and usually a design smell. Do not reflexively convert the block into a `//` comment;
that produced private helpers whose comments merely restated their own names. Keep only what the
code genuinely cannot state (a language subtlety, an unenforced precondition, a cross-assembly
ordering race) and delete the rest.

---

## Phase 4 — Prose

Order by consumer value: public API first, editor tooling later, math/value types last. Per §6.6,
public consumer-facing API takes the multi-line block form; `internal`, editor-only and sample
members keep one sentence but use the inline form only when the complete line fits within 120
columns.

**Write what the signature cannot say.** A summary restating the member name is worse than none.
The ones that earned their place in the recorded run:

- `floatP.Equals` treats NaN as equal to NaN and both zeroes as equal — *deliberately unlike*
  `==`, which is what makes the type usable as a dictionary key
- `RangeAttribute` passes a `null` value, so it needs pairing with `RequiredAttribute`
- `SerializationSecurityMode.Secure` is serialize-only and cannot round-trip
- three `UnitySendMessage` entry points must keep their exact names because the iOS bridges
  dispatch them by string

Where the rationale already lives in a package's `AGENTS.md`, point at it rather than restating it
(§2.7) — one place to drift, not N.

---

## Phase 5 — Scan for what a scripted edit can silently break

Mandatory after any scripted mass edit. Every one of these caught a real self-inflicted defect:

```bash
python3 .agents/skills/code-standards-audit/scripts/post-edit-scan.py
```

It checks: `///` immediately after an attribute line (attaches to nothing — no compiler error);
doc blocks whose lines disagree on indentation; unbalanced `<summary>`; a stray space after
`<summary>`; and UTF-8 BOM drift against HEAD (§2.4 — reading `utf-8-sig` and writing `utf-8`
strips it silently).

**For member moves, prove the reorder lost nothing** by comparing sorted non-blank line multisets:

```bash
diff <(git show HEAD:<file> | sed '/^[[:space:]]*$/d' | sort) \
     <(sed '/^[[:space:]]*$/d' <file> | sort) && echo "pure reorder"
```

Brace counting is *not* a substitute — it produced a false alarm on a 360-line reorder because
multi-line regexes match differently across reordered lines.

---

## Phase 6 — Commit and verify

**Stage explicit paths. Never `git add -A`** (§2.4) — with a concurrent agent it sweeps their work
into your commit under your message, and this has already happened twice. Check
`git status --porcelain` for files you did not touch, and `git diff --cached --stat` before
committing.

One commit per submodule, then one host commit bumping the pointers. Fold CHANGELOG entries into
each package's existing **unpublished** top section using `**Docs**:` (§2.7 pre-publication rule —
no version bumps, no new sections); check `git -C Packages/<pkg> tag --list | tail` against
`package.json` to confirm it is unpublished. Watch for a duplicate `**Docs**:` heading in the same
section and merge if so.

Verify per §2.5 — both environments, Editor half first because both write the same results file:

```bash
Tools/test-all.sh editor        # opens Editor, clears stale results, prints the run snippet
# drive PlayMode via unity-mcp Unity_RunCommand, then:
Tools/test-all.sh editor-save   # BEFORE batch, or compare reads one run twice
# close the Editor, then:
Tools/test-all.sh batch
Tools/test-all.sh compare
```

The evidence is the `distinct runs: …` and `same code: …` lines, not the verdict. If nothing
`.cs`/`.asmdef` changed since a previous batch run, its recorded `.codeid` still applies and only
the Editor half needs re-running — verify the ids match before relying on that. Take warning
counts from the `-runTests` log only (§2.2: test assemblies do not compile in a plain `-quit`
open). A `kill -TERM` on the Editor can leave an orphaned `Temp/UnityLockfile`; remove it only
after `pgrep` confirms no process, or the next liveness check reads it as a running Editor.

Leave `ProjectSettings/ProjectSettings.asset` alone — expected churn from opening the Editor
(§2.4).
