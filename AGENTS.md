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
  - **Sample asmdef boundaries**: Unity disallows asmdef-defined assemblies from referencing `Assembly-CSharp` (and vice-versa) in either direction. When a UPM sample's editor code uses sample runtime types in a generic constraint or `using` (e.g. `class XImporter : AssetsConfigsImporter<SampleEnum, AssetT, SampleSO>`), the sample runtime files MUST live in their own `*.asmdef` so the sample editor asmdef can reference them. Symptom of getting this wrong: `CS0246: type ... could not be found` from inside the sample editor assembly even though the type is right next door. Note also that asmdef references are NOT transitive — if a sample (or any consumer) touches an API that surfaces a type from a third package in its return shape (e.g. `AssetConfigsScriptableObject.Configs` returning `List<Pair<TId, AssetReference>>`, where `Pair<,>` lives in `GameLovers.GameData`), the consumer asmdef must reference that third package directly. Reference: `Packages/com.gamelovers.services/Samples~/AssetResolver/` ships both a runtime asmdef and an editor asmdef, the editor asmdef references the runtime asmdef, and both reference `GameLovers.GameData` for `Pair<,>`.
- **External APIs**: when investigating third-party sources (Unity packages, UniTask, Addressables), prefer local UPM cache under `Library/PackageCache/` when available.
- **Package README accuracy**: when updating or auditing a package `README.md`, always verify every code example, component name, feature claim, and file-tree reference directly against the package's own `AGENTS.md` §2/§3 and the actual `Runtime/` source files before writing. Fabricated or stale examples are a known risk; a recurring drift pattern is README-level marketing copy (types or subsystems that no longer exist in source) outpacing AGENTS/Runtime reality — e.g. the `mobileservices` README once marketed `PointerInputManager` / `Controls/` / "Input System Integration" while the source uses `EnhancedTouch` only.
- **Dependency drift**: when a package's `package.json` dependency changes, cross-check both `README.md` and `AGENTS.md` for stale references to the old package name or version.
- **Package samples**: for code-centric UPM packages (no scene hierarchy, no custom inspectors), inline README code examples are sufficient; a `Samples~/` directory adds maintenance burden without proportional value unless the setup requires a running scene.
- **Sample-scoped editor automation**: when a UPM sample needs editor-side automation (auto-Addressables wiring, asset post-processing, generated content, custom menus/inspector affordances), the editor scripts MUST live inside `Samples~/<Sample>/Editor/` with their own `.asmdef` — never in the package's main `Editor/` assembly. Three contracts to follow: **(1) Lifetime** — sample editor scripts ship as full Editor assemblies into consumer projects, so anything in the package main editor would orphan after sample deletion; one inside the sample folder goes away with the sample. **(2) UPM first-import chicken-and-egg** — an `AssetPostprocessor` shipped inside `Samples~/<Sample>/Editor/` compiles AFTER the import batch that brings it into the consumer's project, so it MISSES its own first invocation against same-batch assets. Pair it with an `[InitializeOnLoadMethod]` safety net, defer both entry points to `EditorApplication.delayCall` (asset modification during `OnPostprocessAllAssets` itself is unsafe), and write the setup state-based-idempotent so subsequent reloads are silent no-ops. **(3) Cross-editor-assembly decoupling** — the package's main `Editor/` assembly must NOT compile-time reference a sample-scoped editor assembly; invoke functionality across the boundary via `EditorApplication.ExecuteMenuItem("Tools/.../<verb>")` and guard the caller-side UI (e.g. an inspector button) with an asset-path check so the entry-point only appears when the inspected context belongs to that sample. Reference: `Packages/com.gamelovers.services/Samples~/AssetResolver/Editor/AssetResolverSampleSetup.cs` + `Packages/com.gamelovers.services/Editor/Inspectors/AssetConfigsScriptableObjectEditor.cs` (`IsAssetResolverSampleConfigs()` path-guarded button calling `ExecuteMenuItem`).
- **Editor namespace collision**: Editor scripts placed in a sub-namespace ending with `.Editor` (e.g., `GameLovers.X.Editor`) MUST qualify the Unity base class as `UnityEditor.Editor`. A bare `Editor` resolves to the enclosing namespace's own `.Editor` child (a namespace), not the Unity type, producing `CS0118: 'Editor' is a namespace but is used like a type`.
- **Unity `.meta` files in git**: when moving or renaming `.cs` files, `git mv` both the `.cs` and `.cs.meta` together to preserve GUIDs. Newly created files/folders (via `mkdir`, code-gen, etc.) will not have `.meta` files until Unity opens the project — commit those `.meta` files in a follow-up pass after the editor regenerates them.
- **Squashing with `git reset --soft`**: before running `git reset --soft <base>`, always `git add -A` any working-tree changes. `--soft` preserves the index as-is and does NOT fold in unstaged edits — a squash done without this step will silently drop working-tree-only changes. Verify via `git diff --cached --stat` before the commit.
- **`LogAssert.Expect` does not suppress console output**: `LogAssert.Expect(LogType, message)` only consumes an expected log for the NUnit pass/fail decision. The log still streams to Unity's Editor console during the run — expected errors and warnings printing alongside a green test suite is normal, not a regression. Do not try to "silence" such logs by wrapping Debug calls; the log-assertion path is the intended contract.
- **Editor UI stack**: for new editor tooling (windows, inspectors, property drawers) in this framework, prefer UIToolkit — `EditorWindow` + UXML + USS + Unity 6 `TabView` for windows; `CreateInspectorGUI()` / `CreatePropertyGUI()` for inspectors and drawers. IMGUI (`OnInspectorGUI` / `OnGUI`) is acceptable only for maintenance of existing tools; do not default to it for new work. Reference implementation: `Packages/com.gamelovers.services/Editor/Explorer/`.
- **UIToolkit `Foldout` header customization**: `foldout.Q<Toggle>()` returns the clickable header row; you can `.Add()` siblings (e.g. action buttons) to it, but click events bubble up to the toggle and would also collapse/expand the foldout every time the user fires the action. Always insert `RegisterCallback<ClickEvent>(evt => evt.StopPropagation())` on every action element added to the toggle row. Reference: `Packages/com.gamelovers.services/Editor/Explorer/Tabs/MessageBrokerTab.cs` — per-message-type `Unsubscribe All` lives on the foldout header next to the type name + count.
- **UIToolkit numeric field label-width pitfall**: the `IntegerField(string label)` / `FloatField(string label)` constructor first arg is a label rendered *inside* the widget at the top, eating most of the interior width — multi-digit numbers render off-screen even at sane widget widths (~130 px). For compact rows, build the row as `Label("Field: ") + naked IntegerField()/FloatField() + (optional) Slider/SliderInt`. Pair the slider with the field via bidirectional `RegisterValueChangedCallback` + `SetValueWithoutNotify` to avoid feedback loops. Reference implementations: `Packages/com.gamelovers.services/Editor/Explorer/Tabs/TimeTab.cs` AddTime row and `Editor/Explorer/Tabs/RngTab.cs` Peek-N + Set-counter rows.
- **Pre-publication versioning**: if a UPM package's current version has not been published/tagged yet, fold new work into the existing `## [X.Y.Z]` `CHANGELOG.md` section rather than creating a new version entry. Do not bump `package.json` `version` and do not add entries to `MIGRATION.md` until the version is actually published. Only create a new `## [X.Y.Z]` section when cutting an actual release.
- **`InternalsVisibleTo` for Unity test-assembly access**: Unity tests in a separate `*.Tests` assembly cannot see `internal` members of their source assembly. Prefer adding an `AssemblyInfo.cs` at the source assembly's root folder with `[assembly: InternalsVisibleTo("<SourceAsm>.Tests")]` over widening the member to `public`. One `AssemblyInfo.cs` is needed per assembly that must grant cross-assembly internal access. Reference: `Packages/com.gamelovers.services/Runtime/AssemblyInfo.cs` (Runtime→Editor) and `Packages/com.gamelovers.services/Editor/AssemblyInfo.cs` (Editor→Editor.Tests).
- **Deleting tracked files inside a submodule**: `git rm Packages/<pkg>/<file>` from the parent repo fails with `fatal: pathspec '...' did not match any files` — the parent doesn't own paths inside a submodule. Always run `git -C Packages/<pkg> rm <relative-path>` from the parent (or `cd` into the submodule first). If the file has working-tree modifications (e.g. you edited it earlier in the same session before deciding to delete), the plain form errors with `the following file has local modifications`; resolve with `git -C Packages/<pkg> rm -f <relative-path>` when the intent is to discard both the edits and the file.
- **C# loop-variable closure rename**: when renaming a `foreach` iteration variable that is captured for a closure (e.g. `foreach (var X in list) { var captured = X; btn.clicked += () => Use(captured); }`), `replace_all` every body reference — partial renames of only the `foreach` declaration leave compile errors (`CS0103: The name 'oldVar' does not exist`) on body lines that still reference the old name. The compiler error points at the body usages, not the declaration, so grep the full method body before considering the rename complete.

## 3. Repo structure
- `Assets/`: Unity project assets used for development/testing.
  - `Assets/Samples/`: **imported package samples** (preferred place to work when validating/changing sample content in this host project).
- `Packages/`: Embedded UPM packages (mostly submodules).
- `ProjectSettings/`, `UserSettings/`: Unity configuration.

## 4. Samples workflow (priority order)
When a task references a sample scene/script:
- **1) Work in `Assets/Samples/` first** (this is what the Unity project actually uses when samples are imported).
- **2) If it's not in `Assets/Samples/`**, locate the source sample in the package's `Samples~/` folder:
  - `Packages/<package-name>/Samples~/...` (for embedded/submodule packages in this repo)
  - `Library/PackageCache/<package-name>@<version>/Samples~/...` (for external Unity packages)

## 5. Submodules workflow (important)
If a package folder under `Packages/` is empty, initialize submodules:

```bash
git submodule update --init --recursive
```

When editing a package, treat it like its own repo:
- Make changes inside `Packages/<package-name>/`
- Update that package's `README.md` / `CHANGELOG.md` when behavior or API changes
- Prefer contributing upstream to the package repository

## 6. Package-specific guides (source of truth)
Some packages include their own `AGENTS.md`. When present, **that file is the source of truth** for that package.

Packages with `AGENTS.md`:
- `Packages/com.gamelovers.services/AGENTS.md`
- `Packages/com.gamelovers.uiservice/AGENTS.md`
- `Packages/com.gamelovers.gamedata/AGENTS.md`
- `Packages/com.gamelovers.mobileservices/AGENTS.md`

When a package has a subdirectory with its own distinct conventions (e.g., `Tests/`, `Editor/`), a sub-folder `AGENTS.md` may exist there. The parent `AGENTS.md` will contain a **MUST-read pointer** of the form:
> Before reading, editing, or creating any file in `<X>/`, you **MUST** read [`<X>/AGENTS.md`](<X>/AGENTS.md) first.

## 7. Documentation policy
- Root `README.md` documents **this host repository** and links out to packages.
- Package-level `README.md` documents the **package** (install, usage, API, samples).
- Package-level `AGENTS.md` is the **contributor/agent guide** for that package (architecture, gotchas, workflows).
- **README size threshold**: when a trimmed package `README.md` would exceed ~350 lines, move deep API reference into a sibling `docs/` folder (flat `.md` files + a `docs/README.md` index). The README itself should stay lean: Why / Install / Quick Start / Services-at-a-Glance / Samples / Related docs / Contributing / Support / License. Reference implementations: `Packages/com.gamelovers.uiservice/docs/` and `Packages/com.gamelovers.services/docs/`.

## 8. Claude Code convention
Every package with an `AGENTS.md` also has a `CLAUDE.md` at the package root. `CLAUDE.md` is a thin wrapper that imports `AGENTS.md` via Claude Code's native `@AGENTS.md` syntax — it contains no duplicated content.

When creating a new package with an `AGENTS.md`, also create a matching `CLAUDE.md` following this template:

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

Also create a matching `CLAUDE.md.meta` Unity asset meta file (copy the `TextScriptImporter` pattern from any existing `AGENTS.md.meta`, with a fresh GUID).
