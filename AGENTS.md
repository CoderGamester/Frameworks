# Frameworks (Unity Host Repo) - AI Agent Guide

## 1. Repo overview
This repository is a **Unity 6 host project** used to develop, test, and validate multiple GameLovers UPM packages.

Most packages live under `Packages/` and are included as **git submodules** (see `.gitmodules`).

## 2. Key rules / standards
- **Unity**: 6000.0+
- **C#**: C# 9.0 syntax; **explicit namespaces** (no global usings)
- **Assembly boundaries**:
  - Runtime code must not reference `UnityEditor`
  - Editor tooling must stay under `Editor/` and Editor assemblies
- **External APIs**: when investigating third-party sources (Unity packages, UniTask, Addressables), prefer local UPM cache under `Library/PackageCache/` when available.
- **Package README accuracy**: when updating or auditing a package `README.md`, always verify every code example directly against the `Runtime/` source files before writing. Fabricated or stale examples are a known risk.
- **Dependency drift**: when a package's `package.json` dependency changes, cross-check both `README.md` and `AGENTS.md` for stale references to the old package name or version.
- **Package samples**: for code-centric UPM packages (no scene hierarchy, no custom inspectors), inline README code examples are sufficient; a `Samples~/` directory adds maintenance burden without proportional value unless the setup requires a running scene.
- **Editor namespace collision**: Editor scripts placed in a sub-namespace ending with `.Editor` (e.g., `GameLovers.X.Editor`) MUST qualify the Unity base class as `UnityEditor.Editor`. A bare `Editor` resolves to the enclosing namespace's own `.Editor` child (a namespace), not the Unity type, producing `CS0118: 'Editor' is a namespace but is used like a type`.
- **Unity `.meta` files in git**: when moving or renaming `.cs` files, `git mv` both the `.cs` and `.cs.meta` together to preserve GUIDs. Newly created files/folders (via `mkdir`, code-gen, etc.) will not have `.meta` files until Unity opens the project — commit those `.meta` files in a follow-up pass after the editor regenerates them.
- **Squashing with `git reset --soft`**: before running `git reset --soft <base>`, always `git add -A` any working-tree changes. `--soft` preserves the index as-is and does NOT fold in unstaged edits — a squash done without this step will silently drop working-tree-only changes. Verify via `git diff --cached --stat` before the commit.
- **`LogAssert.Expect` does not suppress console output**: `LogAssert.Expect(LogType, message)` only consumes an expected log for the NUnit pass/fail decision. The log still streams to Unity's Editor console during the run — expected errors and warnings printing alongside a green test suite is normal, not a regression. Do not try to "silence" such logs by wrapping Debug calls; the log-assertion path is the intended contract.

## 3. Repo structure
- `Assets/`: Unity project assets used for development/testing.
  - `Assets/Samples/`: **imported package samples** (preferred place to work when validating/changing sample content in this host project).
- `Packages/`: Embedded UPM packages (mostly submodules).
- `ProjectSettings/`, `UserSettings/`: Unity configuration.

## 4. Samples workflow (priority order)
When a task references a sample scene/script:
- **1) Work in `Assets/Samples/` first** (this is what the Unity project actually uses when samples are imported).
- **2) If it’s not in `Assets/Samples/`**, locate the source sample in the package’s `Samples~/` folder:
  - `Packages/<package-name>/Samples~/...` (for embedded/submodule packages in this repo)
  - `Library/PackageCache/<package-name>@<version>/Samples~/...` (for external Unity packages)

## 4. Submodules workflow (important)
If a package folder under `Packages/` is empty, initialize submodules:

```bash
git submodule update --init --recursive
```

When editing a package, treat it like its own repo:
- Make changes inside `Packages/<package-name>/`
- Update that package’s `README.md` / `CHANGELOG.md` when behavior or API changes
- Prefer contributing upstream to the package repository

## 5. Package-specific guides (source of truth)
Some packages include their own `AGENTS.md`. When present, **that file is the source of truth** for that package.

Examples:
- `Packages/com.gamelovers.uiservice/AGENTS.md`
- `Packages/com.gamelovers.services/AGENTS.md`

When a package has a subdirectory with its own distinct conventions (e.g., `Tests/`, `Editor/`), a sub-folder `AGENTS.md` may exist there. The parent `AGENTS.md` will contain a **MUST-read pointer** of the form:
> Before reading, editing, or creating any file in `<X>/`, you **MUST** read [`<X>/AGENTS.md`](<X>/AGENTS.md) first.

## 6. Documentation policy
- Root `README.md` documents **this host repository** and links out to packages.
- Package-level `README.md` documents the **package** (install, usage, API, samples).


