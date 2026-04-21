---
name: unity-package-merge
description: Absorb one GameLovers UPM package into another end-to-end — git history strategy, folder/namespace reorg, asmdef updates, MIGRATION.md authoring, test updates, host-repo submodule cleanup, and a single clean squashed commit on develop. Use when asked to merge, consolidate, absorb, fold, or combine one package under `Packages/` into another.
---

# Unity Package Merge

Runs a safe, reviewable workflow to absorb one UPM package (the *source*) into another (the *target*) within this Frameworks host repo.

## When to Use

- User asks to "merge", "absorb", "consolidate", "combine", or "fold" one Packages/ entry into another
- A package's scope has drifted and belongs inside an adjacent package
- A small submodule should be retired without losing its functionality

## Preconditions and Hard Rules

- **Target and source must both be under `Packages/`** in this repo (submodule or embedded).
- **Commit identity must be `CoderGamester <game.gamester@gmail.com>`** — verify per-repo local git config before the first commit.
- **Never tag, never promote develop → master, never archive the source repo** — those are manual user actions. The agent stops at a clean commit on `develop` in both target submodule and host repo.
- **Never force-push** any branch.
- Push only `develop`; never push `master` or tags.

## Workflow

### Step 1 — Read both packages and agree scope

Read in parallel:
- `Packages/<target>/package.json`, `README.md`, `CHANGELOG.md`, `AGENTS.md`, `Runtime/*.asmdef`, `Editor/` asmdef (if any)
- `Packages/<source>/package.json`, `README.md`, `CHANGELOG.md`, `Runtime/`, `Editor/`
- Check `.gitmodules` for both submodule URLs

Confirm with user:
- Which package absorbs which? (target = survivor)
- Approach: **(A)** two assemblies in target with `versionDefines`-gated optional assembly, **(B)** single assembly with hard deps, **(C)** one repo with two `package.json` sub-packages, **(D)** keep separate. Approach B is default unless the source has a heavy optional dep that consumers shouldn't inherit.
- Namespace strategy: domain-folder + matching sub-namespace is default; carve-outs (folder for navigation, namespace stays in root) are allowed but must be called out explicitly in the plan.

### Step 2 — Decide git history strategy

Two valid strategies, pick before starting:

1. **Clean squash (default, recommended)**
   - Do the file reorg in the working tree
   - `git reset --soft origin/develop` (only after `git add -A` — see AGENTS.md squash rule)
   - Single commit with all changes
   - No subtree history pulled in, no inherited tags
   - Trade-off: you lose per-file blame from the source package

2. **Preserve subtree history**
   - `git remote add -f <source> <source-url>` then `git subtree add --prefix=_staging_<source> <source>/master`
   - Move files out of staging, delete staging folder
   - Trade-off: develop gets 20–50 extra commits + any tags from the source; tags imported by `git fetch -f` need explicit deletion later

If the source package is small and heavily refactored during merge (namespace renames, file splits), the blame preservation of strategy 2 has limited value — prefer strategy 1.

### Step 3 — Target folder and namespace plan

Default layout:
```
Packages/<target>/
├── Runtime/
│   ├── *Service.cs           (root, ns <Target>)
│   ├── DependencyInjection/  (carve-out, ns <Target>)
│   ├── <Domain1>/            (ns <Target>.<Domain1>)
│   ├── <Domain2>/            (ns <Target>.<Domain2>)
│   └── <Source>/             (ns <Target>.<Source>)
└── Editor/
    ├── <TargetDomain>/       (ns <Target>.<TargetDomain>.Editor)
    └── <Source>/             (ns <Target>.<Source>.Editor)
```

Set `"rootNamespace": "<Target>"` on the asmdef so Unity auto-derives correct namespaces for new scripts.

### Step 4 — Move and re-namespace files

Use `git mv` to move both `.cs` and `.cs.meta` together (preserves GUIDs — critical for any `ScriptableObject` assets referenced downstream).

For each moved file:
- Rewrite `namespace <OldNs>` → `namespace <NewNs>`
- Add/update `using` directives for cross-folder references
- Concrete `<X>Service` classes at `Runtime/` root need `using <Target>.<Domain>;` for interfaces that moved to sub-namespaces

Re-namespace any emitted code-gen strings (scan for `"using <OldNs>"` inside string literals).

### Step 5 — Update asmdefs

- Target runtime asmdef: set `rootNamespace`, add GUID refs for any dependencies the source contributed (Addressables, UniTask, etc.)
- If the source had its own Editor asmdef with special refs (e.g. `Unity.Addressables.Editor`), create or update the target's Editor asmdef
- Test asmdefs: extend with the new GUID refs so tests can construct types from the absorbed code
- Delete the source package's asmdefs after moves

### Step 6 — Update `package.json`, docs, migration guide

- Bump target `version` per SemVer (typically major: namespaces change = breaking)
- Add new hard dependencies from the source
- Update `description` to mention absorbed functionality
- Update `README.md` with a new section for the absorbed feature surface
- Update `AGENTS.md` interface-to-concrete table (add a namespace column if mixing) and folder layout section
- Update `Tests/AGENTS.md` test directory listing if new tests were added
- Create `MIGRATION.md` with before/after `using` diffs for every breaking namespace change; renumber sections if additional breaking changes emerge during review

### Step 7 — Update / add tests

- For every moved pool/command/etc. test file, add the required `using <Target>.<Domain>;` for the new sub-namespaces
- Add unit tests for code that is unit-testable without Unity runtime fixtures (constructors, registry logic, pure helpers)
- Integration tests that require live Unity subsystems (Addressables, etc.) should be marked `[Explicit]` with a clear comment on what fixture is needed
- Do NOT write tests that use `ScriptableObject.CreateInstance<X>()` for types that aren't actually `ScriptableObject` subclasses (e.g., `Sprite`, `Material`) — that throws at runtime

### Step 8 — Verify git identity, commit, repoint host

```bash
# in target submodule
git config user.name  "CoderGamester"
git config user.email "game.gamester@gmail.com"
git log -1 --format='%an <%ae>'  # verify last local commit (if any) uses this identity
```

Commit with a descriptive message that lists:
- Source package + version absorbed
- New folder/namespace layout
- File splits applied
- Breaking changes (per `MIGRATION.md`)

In the host repo:
```bash
git add Packages/<target>        # refresh submodule pointer to new SHA
git submodule deinit -f Packages/<source>
git rm -f Packages/<source>
rm -rf .git/modules/Packages/<source>
```
Then edit `.gitmodules` to remove the `[submodule "Packages/<source>"]` block and clean `Packages/packages-lock.json` if it references the old source package.

Commit on host `develop` with a `chore: merge <source> into <target>` message.

### Step 9 — Stop at develop

Do NOT:
- Create any git tag on the target repo
- Merge, rebase, or fast-forward `develop` into `master` on either repo
- Archive the source repo on GitHub

Inform the user that those steps are their responsibility and provide the push commands:

```bash
cd Packages/<target> && git push origin develop
cd ../.. && git push origin develop
```

### Step 10 — Unity compile pass

Ask the user to open Unity once so it regenerates `.meta` files for any newly created files/folders. Those `.meta` files must be committed in a follow-up pass (either amended into the same commit if not yet pushed, or as a new commit if already pushed).

## Common Pitfalls

- **Dropped usings during namespace rename**: After `sed`-based namespace rewrites, re-check that no `using System.Collections;`, `using Cysharp.Threading.Tasks;`, or `using UnityEditor;` was accidentally stripped. See root `AGENTS.md` for known Unity-specific collisions.
- **`*.Editor` sub-namespace shadows `UnityEditor.Editor`** — qualify as `UnityEditor.Editor` (see root `AGENTS.md`).
- **Silent squash loss via `git reset --soft` without prior `git add -A`** (see root `AGENTS.md`).
- **Imported tags from subtree source** — delete explicitly with `git tag -d <imported-tag>` before first push.
- **`mkdir` creates folders with no `.meta`** — Unity generates those on editor load. Commit them in a follow-up.
- **Generated code-gen strings** — scan for `"using <OldNs>"` inside string literals of any generator scripts (emitted into downstream generated `.cs` files). These must be updated even though they're "just strings".

## Done When

- Target repo `develop` has a single clean commit (strategy 1) or a set of clean commits ending in a single merge-intent commit (strategy 2)
- Source submodule removed from host `.gitmodules` and `.git/modules/`
- `packages-lock.json` and `.gitmodules` in host repo are clean
- `MIGRATION.md` exists in the target package with all namespace/location breaking changes
- Both `develop` branches are pushed (by the user) and no tagging/master/archival action was taken by the agent
