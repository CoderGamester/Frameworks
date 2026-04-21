---
name: package-docs-audit
description: Audit and rewrite a GameLovers UPM package's README.md and AGENTS.md by verifying every code example and API reference against the actual Runtime source files. Use when asked to improve, update, review, or fix documentation for any package under Packages/ in this repo.
---

# Package Docs Audit

Audits and rewrites a GameLovers UPM package's `README.md` and `AGENTS.md` so they accurately reflect the real runtime API.

## When to Use

- User asks to "improve", "update", "fix", or "review" docs for a package under `Packages/`
- A README code example looks suspicious or outdated
- A new service was added but docs weren't updated
- The package dependency changed (check `package.json`)

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
- Version badge must match `package.json` version

**AGENTS.md** (contributor/agent-facing):
- Section 2 must list all services with correct method names
- Section 4 gotchas must reflect actual runtime behavior
- Section 3 file list must include all Runtime files

## Package Location Hints

- Embedded submodules: `Packages/<com.gamelovers.package-name>/`
- External packages: `Library/PackageCache/<package>@<version>/`
- If a `Packages/` folder is empty, run: `git submodule update --init --recursive`
