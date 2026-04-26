---
name: package-docs-audit
description: Audit, align, and rewrite a GameLovers UPM package's README.md, AGENTS.md, and CLAUDE.md by verifying every code example and API reference against the actual Runtime source files, applying the repo-wide three-file convention (README/AGENTS/CLAUDE), and splitting deep API reference into a docs/ folder when the README exceeds ~350 lines. Use when asked to improve, update, review, fix, align, or rewrite documentation for any package under Packages/ in this repo.
---

# Package Docs Audit

Audits, aligns, and rewrites a GameLovers UPM package's `README.md`, `AGENTS.md`, and `CLAUDE.md` so they accurately reflect the real runtime API and follow the repo-wide documentation convention.

## When to Use

- User asks to "improve", "update", "fix", "review", "align", or "rewrite" docs for a package under `Packages/`
- A README code example looks suspicious or outdated
- A new service was added but docs weren't updated
- The package dependency changed (check `package.json`)
- A package has an `AGENTS.md` but no `CLAUDE.md` wrapper yet
- A README has grown oversized (>350 lines) and deep API reference should move to `docs/`

## Documentation Convention (repo-wide)

Every package with an `AGENTS.md` must have three files at its root:

| File | Audience | Role |
|------|----------|------|
| `README.md` | End users | Why / Install / Quick Start / Services-at-a-Glance / Samples / Related docs / Contributing / Support / License |
| `AGENTS.md` | AI agents + contributors | Single source of truth for architecture, gotchas, workflows |
| `CLAUDE.md` | Claude Code | Thin wrapper — `@AGENTS.md` import only, never duplicates content |

Reference implementations: `com.gamelovers.services`, `com.gamelovers.uiservice`, `com.gamelovers.gamedata`, `com.gamelovers.mobileservices`.

## Workflow

### Step 1 — Read the package

Read these files in parallel:
- `Packages/<pkg>/README.md`
- `Packages/<pkg>/AGENTS.md`
- `Packages/<pkg>/package.json` (version + dependencies)
- `Packages/<pkg>/CHANGELOG.md` (recent API changes)

### Step 2 — Read all Runtime source files

Read **every `.cs` file** under `Packages/<pkg>/Runtime/` to extract the exact public API:
- Interface names and method signatures
- Constructor signatures
- Property names and types
- Which methods are synchronous vs async
- Namespace

Do not trust existing docs — treat the source as ground truth.

### Step 3 — Cross-reference and identify inaccuracies

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

For `AGENTS.md`, also check:
- Are all services listed in Section 2 (including newer ones)?
- Are method names exact matches to the source?
- Are gotchas up to date with source behavior?

### Step 4 — Report findings (if user wants to review first)

Group by severity:
- **Critical** — code won't compile or will mislead users about the API
- **Stale** — outdated names, versions, dependency references
- **Missing** — services, interfaces, or methods not documented

### Step 5 — Rewrite both files

**README.md** (user-facing):
- Every code example must compile against the real API
- Key Components table must include all public interfaces
- Dependency listed must match `package.json`
- Version badge should be dynamic (`https://img.shields.io/github/v/tag/<owner>/<repo>?label=version`) pointing to `CHANGELOG.md` — avoid hardcoded version strings that go stale
- Section order: Why → System Requirements → Installation → Key Components → Quick Start → Services at a Glance → Samples → Related docs → Contributing (1 paragraph + `AGENTS.md` link) → Support → License
- End with a `## Related docs` table linking to `AGENTS.md`, `CHANGELOG.md`, `MIGRATION.md` (where present), and `docs/README.md` (where present)

**AGENTS.md** (contributor/agent-facing):
- Starts with a `> **Companion files**: CLAUDE.md wraps this file for Claude Code — edit AGENTS.md, not CLAUDE.md. README.md is the user-facing entry point.` blockquote at the very top, below the H1
- Section 2 must list all services with correct method names
- Section 4 gotchas must reflect actual runtime behavior
- Section 3 file list must include all Runtime files
- If the package has a `Tests/AGENTS.md`, cross-link it with a MUST-read pointer of the form:
  > Before reading, editing, or creating any file in `Tests/`, you **MUST** read [`Tests/AGENTS.md`](Tests/AGENTS.md) first.

### Step 6 — Create or update `CLAUDE.md` (if missing)

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

### Step 7 — Decide if `docs/` split is needed

Check the trimmed `README.md` line count. If it exceeds ~350 lines, move deep per-service/per-feature API reference into a sibling `docs/` folder:

- Flat layout: one `.md` per service/feature at `docs/<topic>.md` (no nested folders)
- `docs/README.md` index listing all topic files in a table
- Each topic file starts with `[← Back to index](README.md)` for navigation
- The package `README.md` then keeps only one short example per service in "Services at a Glance" and links to `docs/` for depth

Reference: `Packages/com.gamelovers.uiservice/docs/` and `Packages/com.gamelovers.services/docs/`.

### Step 8 — Verify intra-repo markdown links

Before declaring the audit done, verify every relative markdown link in the edited files resolves. Quick check:

```bash
for f in Packages/<pkg>/{README,AGENTS,CLAUDE}.md; do
  rg -oN '\]\(([A-Za-z][^)]*\.md[^)]*)\)' -r '$1' "$f" | while read link; do
    file=$(echo "$link" | sed 's/#.*//')
    [[ "$file" == http* ]] && continue
    [ -e "$(dirname $f)/$file" ] || echo "BROKEN in $f: $link"
  done
done
```

Also verify any new `docs/` folder: run the same check scoped to `Packages/<pkg>/docs/*.md`.

## Package Location Hints

- Embedded submodules: `Packages/<com.gamelovers.package-name>/`
- External packages: `Library/PackageCache/<package>@<version>/`
- If a `Packages/` folder is empty, run: `git submodule update --init --recursive`
