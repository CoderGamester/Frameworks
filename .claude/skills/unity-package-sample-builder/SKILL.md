---
name: unity-package-sample-builder
description: Author, restructure, build, or validate Unity Package Manager samples under `Samples~`, including single-scene samples, typed multi-scene catalogs, Build Settings or Build Profile preparation, temporary sample build contexts, and package-owned Android/iOS native generation. Use when adding or merging samples, changing sample scene discovery or navigation, eliminating hard-coded asset GUIDs/paths, contributing sample-only native requirements, modifying sample build callbacks, changing a UPM dependency or supported Unity versions, making an imported sample ready to play, or diagnosing behavior that exists only after Package Manager import.
---

# Unity Package Sample Builder

Build UPM samples as removable consumer artifacts. Start with lifetime and assembly ownership, then load only the reference needed for the requested work.

## Required workflow

### 1. Read repository guidance

Read the workspace `AGENTS.md`, the package `AGENTS.md`, and any sample-local instructions before editing. Preserve package-specific Unity versions, render-pipeline constraints, assembly conventions, and documentation policy.

### 2. Classify ownership before choosing a folder or dependency

Write down the owner and lifetime of every new or moved component:

| Owner | May contain |
|---|---|
| Package runtime | Public/player APIs needed without a sample |
| Package Editor | Production configuration and tooling needed whenever the package is installed |
| Sample runtime | Demonstration components and shared sample-player behavior |
| Sample Editor | Scene-aware menus, import setup, navigation bridges, simulator adapters, and sample-only build preparation |

Apply these dependency rules:

- Runtime assemblies never reference Editor assemblies.
- Package assemblies never reference optional sample assemblies.
- Sample Editor assemblies may reference package Editor APIs intended as extension points.
- Anything that must disappear when the imported sample is deleted belongs to the sample.
- Anything production consumers need without importing the sample stays in the package.
- Prefer a sample contributing declarative or temporary configuration to a sample owning a competing production processor.

When a UPM dependency or supported Unity stream changes, read [references/compatibility-and-dependencies.md](references/compatibility-and-dependencies.md). Map the dependency to the assembly and artifact that actually needs it; a package present in the development host does not prove this package owns that dependency.

Read [references/sample-lifecycle.md](references/sample-lifecycle.md) for merged bundles, sample editor automation, build preparation, import/deletion behavior, and acceptance checks.

When a sample has player-build automation, scene identity lookup, a single-scene build contract, a multi-scene catalog, temporary configuration, or native requirements, read [references/build-and-native-ownership.md](references/build-and-native-ownership.md). This is one workflow: choose the single-scene or catalog shape inside it rather than creating another skill or processor.

### 3. Select only the applicable track

- Classify authored runtime UI as UI Toolkit/InputForUI or uGUI/EventSystem before applying an input recipe. Do not add a uGUI EventSystem to a Unity 6 UI Toolkit sample unless an observed requirement proves InputForUI is insufficient.
- For authoring uGUI/TMP prefabs or replacing runtime-built UI, read [references/prefab-ui.md](references/prefab-ui.md).
- For Addressables, generated registries, or first-import setup, read [references/consumer-automation.md](references/consumer-automation.md).
- For scene catalogs, build preparation, temporary build contexts, or Android/iOS requirements, read [references/build-and-native-ownership.md](references/build-and-native-ownership.md).
- For known Unity/sample failure modes, consult [references/pitfalls.md](references/pitfalls.md) only when the symptom or implementation touches that area.
- For visible or interactive behavior, invoke the project `unity-play-verify` skill before claiming completion.

Do not load every reference by default.

### 4. Implement within the selected ownership boundary

Keep changes narrowly scoped. Preserve stable scene and asset GUIDs when reorganizing a sample. Move `.meta` files with their assets. Give imported sample runtime/editor code explicit asmdefs when either side crosses an assembly boundary.

For sample-scoped editor automation:

- Put it under `Samples~/<Bundle>/Editor/` with an Editor-only asmdef.
- Self-locate by type/GUID rather than hardcoding `Assets/Samples/<package>/<version>/...`.
- Account for the first-import chicken-and-egg: an imported `AssetPostprocessor` misses the batch that imports its own source. Pair it with a deferred `[InitializeOnLoadMethod]` safety net when automatic first-import setup is required.
- Make every setup operation state-based and idempotent.
- Avoid compile-time references from the package Editor assembly back to the sample.
- Resolve Unity assets from serialized object references. Do not copy scene GUIDs or sample-relative asset paths into C# or shell lookup logic.
- Validate every catalog/configuration and manual-management decision before changing Build Settings, Build Profiles, or generated native files.

### 5. Validate the imported artifact

`Samples~` does not compile as part of the package. Verification must exercise the actual Package Manager import or an equivalent scratch copy under `Assets/`.

Require all applicable evidence:

- Imported runtime and Editor asmdefs compile.
- Every supported scene opens and plays independently.
- Supported combined navigation/build preparation works.
- Serialized scene identity survives a move/rename when build automation exists.
- Temporary build requirements leave persisted configuration byte-identical and are cleaned after success, failure, and cancellation.
- Native generation is duplicate-free on a second identical pass and preserves consumer-owned non-empty values.
- Real pointer input, content dragging, and visible state are verified through `unity-play-verify`.
- Deleting the imported sample removes its assemblies, menus, callbacks, and scene-specific hooks while package production tooling remains available.
- The sample ships no test assembly unless the user and package policy explicitly require one.
- Routine sample actions appear in on-screen status/activity UI rather than using Console logs as the user experience.

For dependency or support-matrix changes, also require clean consumer hosts for every supported validation editor. The main development host may resolve a removed dependency transitively through unrelated packages. Record the clean host's editor identity, direct manifest, resolved lock, imported sample path, compile result, and behavioral evidence.

### 6. Update documentation in lockstep

Treat each `package.json` `samples[]` entry as one documentation unit by default. A multi-view bundle owns one canonical README at the imported sample root, with anchored sections for its views; create per-view READMEs only when the views are independently importable samples. Update the package sample declaration, canonical sample README, package docs, `AGENTS.md`, and current unpublished changelog entry as required by repository policy. Do not describe setup or verification that was not observed.

## Completion gate

Do not call a sample ready because source files exist, its direct handlers can be invoked, or the package test suite is green. A ready UPM sample has been imported, compiled, played, interacted with, visually inspected, and removed cleanly.
