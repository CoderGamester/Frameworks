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

## 6. Documentation policy
- Root `README.md` documents **this host repository** and links out to packages.
- Package-level `README.md` documents the **package** (install, usage, API, samples).


