# Contributing

Thanks for helping improve GameLovers packages.

This repository is a **Unity host project** that contains multiple UPM packages under `Packages/`, most of which are **git submodules**.

## Where to contribute

- **Package changes**: contribute to the package repository (preferred). In this host repo, packages are typically mounted at:
  - `Packages/com.gamelovers.*`
- **Host-project changes**: contribute here if the change is about:
  - Unity project setup, sample scenes that live under `Assets/`, or project-level CI/docs

## Setup

### Clone with submodules

```bash
git clone --recurse-submodules <repo-url>
```

If you already cloned:

```bash
git submodule update --init --recursive
```

### Unity version

- Use **Unity 6000.0+** (see `ProjectSettings/ProjectVersion.txt`).

## Coding standards

- **C#**: C# 9.0
- **Namespaces**: explicit namespaces (no global usings)
- **Runtime vs Editor**:
  - Runtime code must not reference `UnityEditor`
  - Editor tooling must live under `Editor/` and Editor assemblies
- **Async**: prefer UniTask for packages that use async flows

## Documentation expectations

- If you change behavior/public API, update:
  - Package `README.md` (usage / examples)
  - `CHANGELOG.md` (user-facing changes)
  - Any package `AGENTS.md` guidance if architecture or workflows changed

Root `README.md` should stay focused on **this host repo** and link out to package docs.

## Pull requests

- Keep PRs focused and small when possible.
- Include:
  - Motivation / context
  - What changed
  - How to validate (steps, tests, screenshots if UI/editor related)

## Licensing

- This repository is licensed per the root `LICENSE`.
- Packages under `Packages/` may have their own licenses; those govern the package contents.


