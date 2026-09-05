---
name: package-docs-audit
description: Audit, align, and rewrite GameLovers UPM package documentation and metadata. Verify README examples, install instructions, dependency resolution, compatibility evidence, links, samples, public symbols, package.json descriptions, and changelog placement against source and consumer hosts. Use for package or framework README modernization and whenever APIs, dependencies, samples, install URLs, or supported Unity streams change.
---

# Package Docs Audit

Audits and aligns every user-facing and contributor-facing document shipped by a GameLovers UPM package. Source and package metadata are the ground truth; existing prose is evidence to verify, not authority.

## When to Use

- User asks to "improve", "update", "fix", "review", "align", or "rewrite" docs for a package under `Packages/`
- A README code example looks suspicious or outdated
- A new service was added but docs weren't updated
- The package dependency changed (check `package.json`)
- A symbol, serialized field, sample path, setup mechanism, or supported Unity stream was removed or renamed
- Multiple scenes or controller folders were merged into one importable sample
- A package has an `AGENTS.md` but no `CLAUDE.md` wrapper yet
- A README has grown oversized (>350 lines) and deep API reference should move to `docs/`

## Documentation Convention (repo-wide)

Every package with an `AGENTS.md` must have three files at its root:

| File | Audience | Role |
|------|----------|------|
| `README.md` | End users | Outcome / fit / compatibility / install / first success / lifecycle and limits / samples / help |
| `AGENTS.md` | AI agents + contributors | Single source of truth for architecture, gotchas, workflows |
| `CLAUDE.md` | Claude Code | Thin wrapper — `@AGENTS.md` import only, never duplicates content |

Reference implementations: `com.gamelovers.services`, `com.gamelovers.uiservice`, `com.gamelovers.gamedata`, `com.gamelovers.mobileservices`.

## Workflow

### Step 1 — Read the package and documentation inventory

Read these files in parallel:
- `Packages/<pkg>/README.md`
- `Packages/<pkg>/AGENTS.md`
- `Packages/<pkg>/package.json` (version + dependencies)
- `Packages/<pkg>/CHANGELOG.md` (recent API changes)
- every Markdown file under `Packages/<pkg>/docs/` and `Packages/<pkg>/Samples~/`
- every `package.json` `samples[]` entry and its imported root
- the host `.gitmodules`, `Packages/manifest.json`, and `Packages/packages-lock.json`
- the package's canonical Git remote, available tags, and current branch state

The host is not installation evidence. Embedded packages and unrelated direct dependencies can make an invalid consumer graph appear healthy.

### Step 2 — Read affected source and public API

For a full package audit, read every `.cs` file under `Runtime/`. For a diff-scoped update, read every changed source file plus the declarations referenced by changed documentation. Extract:
- Interface names and method signatures
- Constructor signatures
- Property names and types
- Which methods are synchronous vs async
- Namespace
- Serialized fields and setup mechanisms described by docs, even when they are not public API

Build a deleted/renamed-symbol list from the diff and search all package Markdown for each old identifier, path, dependency, and setup phrase. Removing a field from source without removing its documentation is a failed audit.

Do not trust existing docs — treat the source as ground truth.

### Step 3 — Establish installation and compatibility truth

Before editing install or compatibility prose:

1. Resolve the canonical repository URL from `.gitmodules` and the package remote. Confirm the README URL and pinned tag exist.
2. Build the exact clean-consumer manifest the README asks a user to install. A Git UPM dependency does not make its own Git dependencies transitively installable; internal semver dependencies need a configured registry or an additional direct Git entry.
3. Compare the clean graph with the development host's manifest and lock. Record dependencies the host embeds or installs directly and therefore masks.
4. Distinguish the package's declared dependency from the effective resolved floor. Do not advertise an older effective dependency than the clean lock resolves.
5. Use these terms consistently:
   - **Minimum**: the `package.json` `unity` value; it is one floor, not a supported-version list.
   - **Reference streams**: editor families selected for validation.
   - **Validated editor**: an exact editor patch with attributable, current evidence for the same source identity.
   - **Primary development editor**: the editor normally used by maintainers; it is not the minimum.
6. Classify every matrix cell as `PASSED`, `FAILED`, or `NOT VALIDATED`. Licensing, network, unavailable-editor, and harness failures are `NOT VALIDATED`, never package failures or passes.

Never write “supported”, “validated”, “tested”, or a validation date from static inspection alone. A target matrix may be documented as planned, but its unvalidated cells must be labeled honestly.

### Step 4 — Cross-reference and identify inaccuracies

For each code example in `README.md`, check:

| Check | Common failure modes |
|-------|---------------------|
| Method names | Invented names, renamed methods, wrong casing |
| Signatures | Wrong argument order, missing/extra parameters, wrong types |
| Async/sync | `await` on synchronous methods, or missing `await` |
| Key strategy | String keys where type keys are used, or vice versa |
| Interface split | `IFoo` vs `IFooManipulator` — wrong interface for the use case |
| Dependencies | Old package name in prose/examples after `package.json` changed |
| Version badge | Badge version doesn't match `package.json` version |
| Constructor | Wrong arguments, missing required parameters |
| Install graph | Dependency only works because the host embeds or directly installs it |
| Compatibility | Minimum version presented as validation, or infra failure presented as pass/fail |
| Repository links | Display name guessed as repository slug, wrong tag prefix, dead issue URL |

For `AGENTS.md`, also check:
- Are all services listed in Section 2 (including newer ones)?
- Are method names exact matches to the source?
- Are gotchas up to date with source behavior?

For samples, treat each `package.json` `samples[]` entry as one documentation unit by default. Require a canonical README inside the imported root; multi-view folders use anchored sections rather than duplicate controller/view READMEs unless those folders are independently importable entries.

For `package.json` metadata, require a durable description of the package's purpose and scope. Do not put Unity version numbers, badges, release status, or marketing claims in `description`; compatibility belongs in `unity` and the README matrix.

### Step 5 — Report findings (if user wants to review first)

Group by severity:
- **Critical** — code won't compile or will mislead users about the API
- **Stale** — outdated names, versions, dependency references
- **Missing** — services, interfaces, or methods not documented

### Step 6 — Rewrite the affected documentation surfaces

**README.md** (user-facing):
- Every code example must compile against the real API
- Cover the user-decision-relevant public surface; do not inventory every interface merely because it is public
- Dependency listed must match `package.json`
- Version badge should be dynamic (`https://img.shields.io/github/v/tag/<owner>/<repo>?label=version`) pointing to `CHANGELOG.md` — avoid hardcoded version strings that go stale
- Prefer this compact order: outcome → use this when / not intended for → compatibility and dependencies → pinned installation → compile-ready first success → concepts, ownership, lifecycle, and limitations → samples → troubleshooting and support
- Link end users to `CONTRIBUTING.md` when it exists. Do not present `AGENTS.md` as end-user documentation.
- Keep deep API catalogs in `docs/`; the README should help a reader decide, install, and succeed

**AGENTS.md** (contributor/agent-facing):
- Starts with a `> **Companion files**: CLAUDE.md wraps this file for Claude Code — edit AGENTS.md, not CLAUDE.md. README.md is the user-facing entry point.` blockquote at the very top, below the H1
- Section 2 must list all services with correct method names
- Section 4 gotchas must reflect actual runtime behavior
- Section 3 file list must include all Runtime files
- If the package has a `Tests/AGENTS.md`, cross-link it with a MUST-read pointer of the form:
  > Before reading, editing, or creating any file in `Tests/`, you **MUST** read [`Tests/AGENTS.md`](Tests/AGENTS.md) first.

### Step 7 — Create or update `CLAUDE.md` (if missing)

Every package with an `AGENTS.md` must have a sibling `CLAUDE.md` at the package root. It is a thin import wrapper — never duplicate content.

**Template:**

```markdown
# Claude Code Guide — <package-display-name>

This package's contributor/agent guide lives in `AGENTS.md`.
Claude Code will automatically import it below.

@AGENTS.md

## Claude-Specific Notes

- Treat `AGENTS.md` as the source of truth.
- If anything in this file appears to conflict with `AGENTS.md`, prefer `AGENTS.md`.
- For user-facing usage, see `README.md`.
```

### Step 8 — Decide if `docs/` split is needed

Check the trimmed `README.md` line count. If it exceeds ~350 lines, move deep per-service/per-feature API reference into a sibling `docs/` folder:

- Flat layout: one `.md` per service/feature at `docs/<topic>.md` (no nested folders)
- `docs/README.md` index listing all topic files in a table
- Each topic file starts with `[← Back to index](README.md)` for navigation
- The package `README.md` then keeps only one short example per service in "Services at a Glance" and links to `docs/` for depth

Reference: `Packages/com.gamelovers.uiservice/docs/` and `Packages/com.gamelovers.services/docs/`.

### Step 9 — Reconcile the changelog

Inspect tags and the package version before choosing a heading:

- If the current version has never been tagged or published, fold documentation changes into that existing pending version.
- If the current version is already published, use the repository's existing pending convention (`Unreleased` where that convention exists) until a later release task chooses a new version.
- Never invent a release number, tag, or date during a documentation-only task.

### Step 10 — Run the documentation verifier

Use the bundled verifier rather than an ad-hoc link regex:

```bash
python3 .agents/skills/package-docs-audit/scripts/check_docs.py Packages/<pkg>
python3 .agents/skills/package-docs-audit/scripts/check_docs.py --base origin/master Packages/<pkg>
python3 .agents/skills/package-docs-audit/scripts/check_docs.py --self-test
```

It checks JSON metadata, package-description version leakage, sample inventory, relative files and heading anchors, compatibility notices, and Unity `.meta` coverage for newly added sample assets. Use `--base` for committed branch/release diffs. Treat the verifier as code: run its polarity fixture before trusting a clean result.

Then compile each executable README snippet in the assembly context it claims to target. A text/link check cannot prove C# examples compile.

### Step 11 — Verify removal and migration references

The bundled verifier covers relative Markdown files and heading anchors throughout the package. Separately search the complete documentation corpus for removed identifiers because a stale historical name can remain valid text and therefore cannot be detected as a broken link.

For sample bundles, also verify:

- The number and location of READMEs agree with `package.json` sample entries and package policy.
- Links into a canonical sample README resolve to existing heading anchors.
- Removed README paths and per-view maintenance instructions have zero remaining matches.
- Every removed or renamed source symbol has zero stale documentation matches unless a migration section deliberately names it as historical.

## Completion contract

Report separately:

- documentation checks that passed,
- clean-install or Unity observations that passed with exact source/editor identities,
- remaining `NOT VALIDATED` cells or visual/platform gates.

Do not collapse those categories into one “verified” statement.

## Package Location Hints

- Embedded submodules: `Packages/<com.gamelovers.package-name>/`
- External packages: `Library/PackageCache/<package>@<version>/`
- If a `Packages/` folder is empty, run: `git submodule update --init --recursive`
