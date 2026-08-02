# Frameworks (Unity Host Repo) - AI Agent Guide

## 1. Repo overview
This repository is a **Unity 6 host project** used to develop, test, and validate multiple GameLovers UPM packages.

Most packages live under `Packages/` and are included as **git submodules** (see `.gitmodules`).

## 2. Key rules / standards

### 2.1 Project & language baseline
- **Unity**: 6000.0+
- **Render pipeline**: this host project is **URP-only**. The pipeline of record is `Assets/Settings/URP-Mobile.asset` (+ `URP-Mobile_Renderer.asset`), assigned in `GraphicsSettings.defaultRenderPipeline` and all 6 `QualitySettings` levels; color space is Linear. Only `com.gamelovers.uiservice` declares a hard `com.unity.render-pipelines.universal` dependency — its `Runtime/Rendering/` presenter features (camera stacking, render-texture targets, backdrop blur) genuinely need URP types. `com.gamelovers.gamedata`, `com.gamelovers.services`, `com.gamelovers.statechart`, `com.gamelovers.googlesheetimporter`, and `com.gamelovers.mobileservices` are **deliberately** pipeline-neutral (verified: zero rendering API references in any of them) and stay installable in BiRP/HDRP projects — do not add a URP dependency to any of them without the same justification `uiservice` has. Consumers who import a `uiservice` sample into a BiRP/HDRP project will see a missing-script warning on the sample scene's Main Camera (`UniversalAdditionalCameraData`); this is expected and accepted.
- **C#**: C# 9.0 syntax; **explicit namespaces** (no global usings)
- **Assembly boundaries**:
  - Runtime code must not reference `UnityEditor`
  - Editor tooling must stay under `Editor/` and Editor assemblies
  - **Sample asmdef boundaries**: Unity disallows asmdef-defined assemblies from referencing `Assembly-CSharp` (and vice-versa) in either direction. When a UPM sample's editor code uses sample runtime types in a generic constraint or `using` (e.g. `class XImporter : AssetsConfigsImporter<SampleEnum, AssetT, SampleSO>`), the sample runtime files MUST live in their own `*.asmdef` so the sample editor asmdef can reference them. Symptom of getting this wrong: `CS0246: type ... could not be found` from inside the sample editor assembly even though the type is right next door. Note also that asmdef references are NOT transitive — if a sample (or any consumer) touches an API that surfaces a type from a third package in its return shape (e.g. `AssetConfigsScriptableObject.Configs` returning `List<Pair<TId, AssetReference>>`, where `Pair<,>` lives in `GameLovers.GameData`), the consumer asmdef must reference that third package directly. Reference: `Packages/com.gamelovers.services/Samples~/AssetResolver/` ships both a runtime asmdef and an editor asmdef, the editor asmdef references the runtime asmdef, and both reference `GameLovers.GameData` for `Pair<,>`.
- **C# loop-variable closure rename**: when renaming a `foreach` iteration variable that is captured for a closure (e.g. `foreach (var X in list) { var captured = X; btn.clicked += () => Use(captured); }`), `replace_all` every body reference — partial renames of only the `foreach` declaration leave compile errors (`CS0103: The name 'oldVar' does not exist`) on body lines that still reference the old name. The compiler error points at the body usages, not the declaration, so grep the full method body before considering the rename complete.

### 2.2 Evidence & verification
- **An exit code is not evidence — the artifact is.** Delete the expected output *before* a run, then require it to exist afterwards. A tool that fails can leave a previous run's file in place, and reading it yields confident, wrong answers attributed to the wrong input.
- **Prove freshness before reading a generated file.** Check its timestamp against the run that supposedly produced it. A report that predates your change describes a codebase that no longer exists.
- **Prove attribution before acting on a result.** When a result must map back to a specific input, verify the identifier is unique. Ambiguous keys (duplicate names across scopes, parameterized cases whose reported name differs from the declared one) mis-attribute silently rather than erroring.
- **Never write "verified", "confirmed" or "tested" without a recorded observation.** Applies equally to code comments, docs, commit bodies and reports to the user. An unearned claim is worse than no claim: it stops the next person checking.
- **Count, don't estimate, before quoting a number.** If a number will be acted on, produce it with a command.
- **Validate a rule against the existing corpus before codifying it.** A threshold the codebase violates on the day it is written teaches everyone to ignore the document.
- **Checkpoint before a destructive experiment.** `git checkout` / `restore` / `reset` revert to HEAD, not to your last edit — they will silently discard *other* uncommitted work in the same file. Commit or stash first, especially before any mutate-and-revert loop.
- **When a finding resists the expected remedy, classify it before acting, and require proof of the class.** Heterogeneous findings need different actions; applying one uniform response destroys real signal. Concrete instance: the A5 / D2 / UNFALSIFIABLE verdict table in each package's `Tests/AGENTS.md` §2.
- **Keep the verifier separate from the author.** Self-review reliably misses the bug class you just wrote. Where correctness matters, have a different agent (or a later, adversarial pass) re-derive the result rather than confirm it.

### 2.3 Tooling & environment
- **`Tools/` holds the repo's repeatable scripts** (`coverage.sh`, `coverage-summary.py`). It is not referenced anywhere else in this guide — check it before writing a new one-off script.
- **One Unity project = one lock.** `unity test` takes a project-wide lock, so no two runs can overlap. Parallel agents must not invoke Unity; parallelise analysis and serialise execution.
- **Unity CLI passthrough needs the project argument before `--`**: `unity test . --mode EditMode -- -flag`. Omit the `.` and the first passthrough flag is swallowed as the project path (`Not a Unity project ...`).
- **Unity Code Coverage is sequence-point only**: there is no branch coverage, `nPathComplexity` is emitted as `0` for every method, and CRAP is therefore systematically optimistic. Assembly filters are contains-matched — `-*Tests` does NOT exclude `X.Tests.PlayMode`; use `-*Tests*`.
- **External APIs**: when investigating third-party sources (Unity packages, UniTask, Addressables), prefer local UPM cache under `Library/PackageCache/` when available.

### 2.4 Git & submodules
- **Unity `.meta` files in git**: when moving or renaming `.cs` files, `git mv` both the `.cs` and `.cs.meta` together to preserve GUIDs. Newly created files/folders (via `mkdir`, code-gen, etc.) will not have `.meta` files until Unity opens the project — commit those `.meta` files in a follow-up pass after the editor regenerates them.
- **Squashing with `git reset --soft`**: before running `git reset --soft <base>`, always `git add -A` any working-tree changes. `--soft` preserves the index as-is and does NOT fold in unstaged edits — a squash done without this step will silently drop working-tree-only changes. Verify via `git diff --cached --stat` before the commit.
- **Deleting tracked files inside a submodule**: `git rm Packages/<pkg>/<file>` from the parent repo fails with `fatal: pathspec '...' did not match any files` — the parent doesn't own paths inside a submodule. Always run `git -C Packages/<pkg> rm <relative-path>` from the parent (or `cd` into the submodule first). If the file has working-tree modifications (e.g. you edited it earlier in the same session before deciding to delete), the plain form errors with `the following file has local modifications`; resolve with `git -C Packages/<pkg> rm -f <relative-path>` when the intent is to discard both the edits and the file.

### 2.5 Testing discipline
- **`LogAssert.Expect` does not suppress console output**: `LogAssert.Expect(LogType, message)` only consumes an expected log for the NUnit pass/fail decision. The log still streams to Unity's Editor console during the run — expected errors and warnings printing alongside a green test suite is normal, not a regression. Do not try to "silence" such logs by wrapping Debug calls; the log-assertion path is the intended contract.
- **`InternalsVisibleTo` for Unity test-assembly access**: Unity tests in a separate `*.Tests` assembly cannot see `internal` members of their source assembly. Prefer adding an `AssemblyInfo.cs` at the source assembly's root folder with `[assembly: InternalsVisibleTo("<SourceAsm>.Tests")]` over widening the member to `public`. One `AssemblyInfo.cs` is needed per assembly that must grant cross-assembly internal access. Reference: `Packages/com.gamelovers.services/Runtime/AssemblyInfo.cs` (Runtime→Editor) and `Packages/com.gamelovers.services/Editor/AssemblyInfo.cs` (Editor→Editor.Tests).
- **`.audit-history.md` is local-developer state, never committed**: the `unity-tests-audit` skill writes a per-package `.audit-history.md` at the package root (`Packages/<pkg>/.audit-history.md`) on every audit run. This file is **gitignored at every level of the repo** — every package's `.gitignore` carries a `.audit-history.md` line, and the host root `.gitignore` carries both `.audit-history.md` and `**/.audit-history.md` for nested-path defence-in-depth. New packages added to `Packages/` MUST receive the same `.gitignore` line (no exceptions — preventive, even if no audit has been run yet). If an audit-history file was tracked before this convention applied, untrack with `git -C Packages/<pkg> rm --cached .audit-history.md` (the `--cached` keeps the file on disk; pair with the `.gitignore` line so it stays untracked). Audit "expand" commands read this local-only file; cross-developer audit history is never shared via VCS.

### 2.6 Editor tooling & UIToolkit
- **Editor namespace collision**: Editor scripts placed in a sub-namespace ending with `.Editor` (e.g., `GameLovers.X.Editor`) MUST qualify the Unity base class as `UnityEditor.Editor`. A bare `Editor` resolves to the enclosing namespace's own `.Editor` child (a namespace), not the Unity type, producing `CS0118: 'Editor' is a namespace but is used like a type`.
- **Editor UI stack**: for new editor tooling (windows, inspectors, property drawers) in this framework, prefer UIToolkit — `EditorWindow` + UXML + USS + Unity 6 `TabView` for windows; `CreateInspectorGUI()` / `CreatePropertyGUI()` for inspectors and drawers. IMGUI (`OnInspectorGUI` / `OnGUI`) is acceptable only for maintenance of existing tools; do not default to it for new work. Reference implementation: `Packages/com.gamelovers.services/Editor/Explorer/`.
- **UIToolkit `Foldout` header customization**: `foldout.Q<Toggle>()` returns the clickable header row; you can `.Add()` siblings (e.g. action buttons) to it, but click events bubble up to the toggle and would also collapse/expand the foldout every time the user fires the action. Always insert `RegisterCallback<ClickEvent>(evt => evt.StopPropagation())` on every action element added to the toggle row. Reference: `Packages/com.gamelovers.services/Editor/Explorer/Tabs/MessageBrokerTab.cs` — per-message-type `Unsubscribe All` lives on the foldout header next to the type name + count.
- **`EditorWindow` does not expose `schedule`**: `schedule` (`IVisualElementScheduler`) lives on `VisualElement` only. Calls like `schedule.Execute(() => …).StartingIn(ms)` inside an `EditorWindow` method body fail to compile with `CS0103: The name 'schedule' does not exist in the current context`. Route through `rootVisualElement.schedule.Execute(...)` instead — the panel's own scheduler lives as long as the window. `VisualElement`-derived editor types (e.g. `ServiceTab` / `MobileServiceTab` explorer tab bases) inherit `schedule` directly and can call it bare.
- **`DeviceSimulatorPlugin` platform sync**: when extending Unity's Device Simulator via `UnityEditor.DeviceSimulation.DeviceSimulatorPlugin` and you need to track the user's selected device profile (iOS / Android), prefer polling `Application.platform` on a `VisualElement.schedule.Execute(...).Every(500)` cadence over subscribing to `DeviceSimulator.deviceChanged`. The event's delegate signature is documented inconsistently across Unity 6 minor versions (6.0 / 6.2 / 6.3+ ScriptReference pages describe the event without showing the delegate type), so version-pinned subscriptions risk silent breakage on Unity upgrades. Unity's Device Simulator spoofs `Application.platform` for device-profile picks (`RuntimePlatform.IPhonePlayer` / `RuntimePlatform.Android`) — polling is outcome-equivalent and version-agnostic. Note also that `DeviceSimulatorPlugin` subclasses are auto-discovered across all editor assemblies (no `[Attribute]`, no registration). Reference: `Packages/com.gamelovers.mobileservices/Editor/Explorer/DeviceSimulatorPanel/MobileServicesDeviceSimulatorPlugin.cs`.
- **UIToolkit numeric field label-width pitfall**: the `IntegerField(string label)` / `FloatField(string label)` constructor first arg is a label rendered *inside* the widget at the top, eating most of the interior width — multi-digit numbers render off-screen even at sane widget widths (~130 px). For compact rows, build the row as `Label("Field: ") + naked IntegerField()/FloatField() + (optional) Slider/SliderInt`. Pair the slider with the field via bidirectional `RegisterValueChangedCallback` + `SetValueWithoutNotify` to avoid feedback loops. Reference implementations: `Packages/com.gamelovers.services/Editor/Explorer/Tabs/TimeTab.cs` AddTime row and `Editor/Explorer/Tabs/RngTab.cs` Peek-N + Set-counter rows.

### 2.7 Documentation, samples & versioning
- **Package README accuracy**: when updating or auditing a package `README.md`, always verify every code example, component name, feature claim, and file-tree reference directly against the package's own `AGENTS.md` §2/§3 and the actual `Runtime/` source files before writing. Fabricated or stale examples are a known risk; a recurring drift pattern is README-level marketing copy (types or subsystems that no longer exist in source) outpacing AGENTS/Runtime reality — e.g. the `mobileservices` README once marketed `PointerInputManager` / `Controls/` / "Input System Integration" while the source uses `EnhancedTouch` only.
- **Dependency drift**: when a package's `package.json` dependency changes, cross-check both `README.md` and `AGENTS.md` for stale references to the old package name or version.
- **Package samples**: for code-centric UPM packages (no scene hierarchy, no custom inspectors), inline README code examples are sufficient; a `Samples~/` directory adds maintenance burden without proportional value unless the setup requires a running scene.
- **Sample-scoped editor automation**: when a UPM sample needs editor-side automation (auto-Addressables wiring, asset post-processing, generated content, custom menus/inspector affordances), the editor scripts MUST live inside `Samples~/<Sample>/Editor/` with their own `.asmdef` — never in the package's main `Editor/` assembly. Three contracts to follow: **(1) Lifetime** — sample editor scripts ship as full Editor assemblies into consumer projects, so anything in the package main editor would orphan after sample deletion; one inside the sample folder goes away with the sample. **(2) UPM first-import chicken-and-egg** — an `AssetPostprocessor` shipped inside `Samples~/<Sample>/Editor/` compiles AFTER the import batch that brings it into the consumer's project, so it MISSES its own first invocation against same-batch assets. Pair it with an `[InitializeOnLoadMethod]` safety net, defer both entry points to `EditorApplication.delayCall` (asset modification during `OnPostprocessAllAssets` itself is unsafe), and write the setup state-based-idempotent so subsequent reloads are silent no-ops. **(3) Cross-editor-assembly decoupling** — the package's main `Editor/` assembly must NOT compile-time reference a sample-scoped editor assembly; invoke functionality across the boundary via `EditorApplication.ExecuteMenuItem("Tools/.../<verb>")` and guard the caller-side UI (e.g. an inspector button) with an asset-path check so the entry-point only appears when the inspected context belongs to that sample. Reference: `Packages/com.gamelovers.services/Samples~/AssetResolver/Editor/AssetResolverSampleSetup.cs` + `Packages/com.gamelovers.services/Editor/Inspectors/AssetConfigsScriptableObjectEditor.cs` (`IsAssetResolverSampleConfigs()` path-guarded button calling `ExecuteMenuItem`).
- **XML doc-comment verbosity tier**: verbose `<summary>` + `<remarks>` blocks belong only on **public consumer-facing interfaces** (IntelliSense / Rider-hover discoverability is the load-bearing reason). `internal` types, editor-only types, sample driver classes, and `Editor/` assembly tab/window/builder classes get **one-sentence summaries** that cross-reference `AGENTS.md` (contributor rationale) or `docs/<file>.md` (consumer reference) instead of duplicating architecture text in the class header. Drift control — the rationale lives in one place, not in N class headers. Applied across `com.gamelovers.mobileservices` 2026-05-11 (~145 LoC of XML doc removed from 22 internal/editor-only files); pattern is the standing convention for the GameLovers package family.
- **Pre-publication versioning**: if a UPM package's current version has not been published/tagged yet, fold new work into the existing `## [X.Y.Z]` `CHANGELOG.md` section rather than creating a new version entry. Do not bump `package.json` `version` and do not add entries to `MIGRATION.md` until the version is actually published. Only create a new `## [X.Y.Z]` section when cutting an actual release.

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
- `Packages/com.gamelovers.googlesheetimporter/AGENTS.md`
- `Packages/com.gamelovers.statechart/AGENTS.md`

When a package has a subdirectory with its own distinct conventions (e.g., `Tests/`, `Editor/`), a sub-folder `AGENTS.md` may exist there. The parent `AGENTS.md` will contain a **MUST-read pointer** of the form:
> Before reading, editing, or creating any file in `<X>/`, you **MUST** read [`<X>/AGENTS.md`](<X>/AGENTS.md) first.

## 6.5. CHANGELOG dialect
All packages follow [Keep a Changelog](http://keepachangelog.com/en/1.0.0/) with `## [X.Y.Z] - YYYY-MM-DD` section headings. Sub-heading style has drifted across the family (some packages use canonical `### Added`/`### Changed`/`### Fixed`, others bold-label `**New**:`/`**Changed**:`/`**Fixed**:`, one uses bold-label with no trailing colon). The canonical style going forward, used by the majority of packages, is **bold-label with a trailing colon**: `**New**:`, `**Changed**:`, `**Fixed**:`, `**Docs**:`. Use it for every new CHANGELOG section in every package; do not retroactively rewrite historical sections just to converge the dialect — that's cosmetic churn with no functional value.

## 6.6. Code style & documentation
Mirrored from the `demons` project guide (`~/Desktop/demons/AGENTS.md` §"Code style & documentation") so both codebases read the same. That file is upstream — if the two ever disagree, it wins.

### General C# rules
- **No `goto`**; use guard clauses and early returns over nested `if`/`else`.
- **Prefer deletion over speculative code.** Remove dead fields, callbacks, config, branches, and abstractions; add code only for a current requirement or an enforced invariant. An interface with exactly one implementation and no plausible second is speculative.
- **Prefer generic, reusable helpers over caller-purpose-named ones.** Name shared utilities by what they do, not by the first feature that needed them.
- **Private fields use `_camelCase`** — never `m_*` (reserved for Unity's own serialized YAML names, which we don't control) and never `s_*` for statics; a private static field is still `_camelCase`.
- **Private methods use `PascalCase`**, never an `_underscore` prefix — that prefix is for fields only.
- **Private const strings** are plain `PascalCase`; never `c_` or `SCREAMING_SNAKE_CASE`.
- **`nameof(T)` over string literals** for type-name-derived paths (`Resources.Load`, `AssetDatabase.LoadAssetAtPath`, Addressables keys, log prefixes). A standalone `private const string FooPath = "Foo"` next to a type-derived load is the smell.
- **C# 9 syntax**: no file-scoped namespaces, no global usings, explicit namespaces.

### Code comments
- **Comments are for non-obvious rationale** — trade-offs, invariants, ordering requirements not enforced by the type system, workarounds for external bugs. Never narrate the obvious (`// Increment the counter`).
- **Never explain the change you are making.** Diff context belongs in the commit message; a comment describes the code's permanent state, not how it got there. Wrong: `// An earlier version cached this, which leaked a handler.` Right: `// Resolved twice per open, so it needs no caching.`
- **One sentence usually suffices.** Multi-paragraph rationale is a smell — split the function, rename for self-documentation, or move it to `docs/` behind a one-line pointer.
- **Prefer rewriting unclear code over commenting it.**

### XML documentation rules
- **Document only `public` / `protected` / `internal` types (class, struct, interface, enum) and members (methods, properties).**
- **Never document**: constructors, fields of any kind (const, static, serialized, public, private), private members, generated code.
- **Properties** collapse to a single line: `/// <summary>Current zoom magnitude.</summary>`.
- **Methods and types** always use the multi-line block form, even when the text would fit on one line.
- **Enum values** use `//` inline on the same line as the declaration — never `/// <summary>` above.
- **`<remarks>`** only for non-obvious behaviour, invariants, or "why". Describe durable behaviour, not the current call graph.
- **Do not write** `<param>`, `<returns>`, `<typeparam>`, or `<exception>` unless explicitly asked. (`<paramref>` inside a summary is fine.)
- **`/// <inheritdoc />`** when implementing an interface member or overriding a documented base member; on a *type* that implements an already-documented interface it collapses to a single line.

### Member ordering inside a type
Omit sections that don't apply, but keep this sequence: **public inner types → const fields → static fields → `[SerializeField]` fields → public fields → private fields → properties → constructor → Unity `MonoBehaviour` methods → methods by access**.

Methods by access, strictly: **public static → public override → public abstract → public → internal → protected → private**.

**`internal` is never interleaved with `private`.** An `internal` test-only helper lives in the contiguous `internal` block above the private methods, even when its only caller is two lines away — co-locating it hides which symbols are testable across assembly boundaries. When adding a member, place it by **kind then access**, never next to the related method.

## 7. Documentation policy
- Root `README.md` documents **this host repository** and links out to packages.
- Package-level `README.md` documents the **package** (install, usage, API, samples).
- Package-level `AGENTS.md` is the **contributor/agent guide** for that package (architecture, gotchas, workflows).
- **README size threshold**: when a trimmed package `README.md` would exceed ~350 lines, move deep API reference into a sibling `docs/` folder (flat `.md` files + a `docs/README.md` index). The README itself should stay lean: Why / Install / Quick Start / Services-at-a-Glance / Samples / Related docs / Contributing / Support / License. Reference implementations: `Packages/com.gamelovers.uiservice/docs/` and `Packages/com.gamelovers.services/docs/`.

## 8. Claude Code convention
Every package with an `AGENTS.md` also has a `CLAUDE.md` at the package root. `CLAUDE.md` is a thin wrapper that imports `AGENTS.md` via Claude Code's native `@AGENTS.md` syntax — it contains no duplicated content.

**This applies at every level, not just the package root.** A subfolder `AGENTS.md` (§6) gets a sibling `CLAUDE.md` wrapper too — a bare subfolder `AGENTS.md` is only found if its MUST-read pointer is followed, whereas a nested `CLAUDE.md` is auto-imported by Claude Code the moment work touches that directory. As of 2026-07-31 every package's `Tests/AGENTS.md` has a matching `Tests/CLAUDE.md`; keep that pairing whenever a new subfolder guide is added anywhere in the tree.

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

For a subfolder guide, retarget the last two lines at the parent instead of the package root:

```markdown
# Claude Code Guide — <package-display-name> <Subfolder>

This folder's conventions live in `AGENTS.md`.
Claude Code will automatically import it below.

@AGENTS.md

## Claude-Specific Notes

- Treat `AGENTS.md` as the source of truth.
- If anything in this file appears to conflict with `AGENTS.md`, prefer `AGENTS.md`.
- For package-level architecture, see `../AGENTS.md`.
```

Also create a matching `CLAUDE.md.meta` Unity asset meta file (copy the `TextScriptImporter` pattern from any existing `AGENTS.md.meta`, with a fresh GUID).
