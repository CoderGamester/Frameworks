# Frameworks Unity Host — Agent Guide

## Scope and precedence

This repository is a Unity 6 host used to develop and validate GameLovers UPM packages under `Packages/`, most of which are Git submodules.

- Rules inherit down the directory tree. A child `AGENTS.md` adds local rules; it overrides an ancestor only when it explicitly names the overridden rule.
- Read the nearest package and folder guide before changing files in that scope.
- `README.md` and package `docs/` are consumer documentation. `AGENTS.md` contains contributor constraints, not an API inventory or audit history.
- `CLAUDE.md` files are wrappers around adjacent `AGENTS.md` files. Edit the `AGENTS.md`, not the wrapper.

## Project baseline

- Unity: 6000.0 or newer. C#: C# 9 with explicit namespaces; no file-scoped namespaces or global usings.
- The host project is URP-only, using `Assets/Settings/URP-Mobile.asset` and `URP-Mobile_Renderer.asset` in Linear color space.
- Only `com.gamelovers.uiservice` is URP-dependent. GameData, Services, Statechart, GoogleSheetImporter, and MobileServices must remain render-pipeline-neutral unless their production code gains a justified rendering dependency.
- Runtime assemblies must not reference `UnityEditor`. Editor code belongs under `Editor/` and in editor-only assemblies.
- Asmdef references are not transitive. Any assembly that consumes a type exposed by another assembly's API must reference the owning assembly directly.
- An asmdef assembly cannot reference `Assembly-CSharp`, or vice versa. If sample Editor code uses sample runtime types, the sample runtime needs its own asmdef and the Editor asmdef must reference it. Add direct references for third-party types exposed through inherited or generic API shapes.
- A `CS0012` dependency follows the assembly that owns a referenced base class. A static call on a type derived from an external base can still require that external assembly. Declare honest dependencies; do not move code merely to keep an asmdef artificially dependency-free.
- Use conditional compilation only at real platform/API boundaries. Keep shared validation, ownership, state transitions, and public contracts outside repeated `UNITY_EDITOR` or platform branches.

## Safe repository workflow

- Preserve unrelated working-tree changes. Inspect status before editing and stage explicit paths only; never use `git add .` or `git add -A` during ordinary work.
- Treat each package submodule as its own repository. Before its first edit, verify that `HEAD` is attached to the intended branch and has the expected upstream.
- Do not use `git checkout --`, `git restore`, or `git reset` for mutation experiments in a dirty file. Save the exact patch first or use an isolated worktree so other edits cannot be lost.
- Serialize Git mutations across submodules and inspect partial success before continuing.
- Move Unity assets with their `.meta` files. New Unity-visible assets need stable unique metadata before commit; prefer generation by the intended Unity Editor unless a package sample explicitly requires deterministic hand-authored GUIDs.
- Preserve each edited file's BOM, line endings, and final-newline convention.
- Delete tracked files inside a submodule with `git -C Packages/<package> rm <relative-path>`; the host repository does not own paths below a submodule gitlink.
- Before a deliberate `git reset --soft` squash, stage every intended working-tree change and verify the cached diff. This is the narrow exception where `git add -A` may be required, and only on a quiet, fully inspected tree.
- Opening Unity may dirty `ProjectSettings/ProjectSettings.asset`. Treat that as unrelated generated churn unless the task intentionally changes project settings.

## Unity and verification

- One Unity project has one lock. Never overlap Unity test or Editor runs against this project.
- `Tools/test-all.sh` is the combined batchmode and Editor test workflow. Test assemblies use `UNITY_INCLUDE_TESTS`, so a plain Editor open does not compile or validate them.
- Batchmode and the Editor are distinct environments. Rendering, Addressables state, imported samples, and Editor-only behavior require the relevant environment; do not generalize a pass from one to the other.
- Read the failure artifact before proposing a cause. A successful process exit is insufficient evidence.
- Generated evidence must be fresh, non-empty, immutable per run, and attributable to the current source and input. A comparison must identify both non-empty inputs.
- Delete or allocate a new destination before generating an artifact, then verify its timestamp and embedded identity. A stale file left by a failed process is not evidence.
- A verifier's PASS is not sufficient: it must print the identities and non-empty sizes/counts of the inputs it compared. Polarity-test new measurement and verification tools against cases that must pass and must fail before trusting their output.
- Preserve each failed and successful verification attempt under a distinct run id. Never rename an older artifact into the current run's expected path.
- Keep the verifier separate from the author for correctness-sensitive changes, or perform a later adversarial pass that re-derives the conclusion rather than confirming it.
- Quote measured numbers only from a command or fresh artifact. Use `Tools/coverage.sh` and `Tools/coverage-summary.py` for coverage; steer by runtime assembly results, not the runtime-plus-Editor aggregate.
- Coverage runs require debug code optimization. Read `Report/Summary.xml`; do not sum numbered coverage files, and exclude test assemblies with `-*Tests*` rather than `-*Tests`.
- Mutation records belong under `.test-all/rcr/`, not `/tmp`. Prepared annotation text without a matching observed RED must never be written into a test.
- Visible behavior requires visual verification. Inspect a fresh Game-view capture for task-specific landmarks; compilation and green tests do not prove rendering, layout, animation, or interaction.
- Registration is not effect. A test that proves an item was added to a list, callback, renderer stack, or registry must also assert the engine precondition or observable consequence that makes registration effective.
- Before invoking freshly edited Editor code, force import/compilation and confirm compilation completed. An open Editor may otherwise execute the previous assembly.
- Resolve a running Unity Editor by project path and `Temp/UnityLockfile`, not by bundle identity or a loose process-name match. Never terminate an Editor belonging to another project.
- `Unity_RunCommand` snippets use one top-level class, no nested private types, and no NUnit-returned types. Read durable results from a fresh artifact rather than relying on callback objects lost across domain reload.
- Unity CLI passthrough requires the project argument before `--`, for example `unity test . --mode EditMode -- -flag`.
- Batchmode and Editor PlayMode results can target the same persistent path. Snapshot the Editor artifact before batchmode and require distinct start times and matching content-based source ids before comparing them.
- Before implementing a Unity feature, check in order whether it is already an authorable serialized property, a pipeline-provided feature, or a newer native engine capability.

## Dependencies, compatibility, and samples

- A dependency change needs assembly-level ownership analysis and clean-consumer evidence. The host's resolved package graph can mask missing or unnecessary dependencies.
- Distinguish the minimum Unity floor, a reference stream, and an exactly validated Editor patch. Outcomes are `PASSED`, `FAILED`, or `NOT VALIDATED`; infrastructure failures are not package failures.
- Validate current workspace source and the exact published Git installation separately when both claims matter.
- Package sample source lives under `Packages/<package>/Samples~/`. `Library/PackageCache/` is read-only evidence.
- An imported `Assets/Samples/` copy does not update automatically. After changing `Samples~`, refresh the imported copy, compare it with the source, force a fresh compile, and validate the imported copy that the host runs.
- Sample editor automation belongs inside the sample's own `Editor/` assembly so it is removed with the sample. Design first-import setup as deferred and idempotent.
- Never mutate authored `ScriptableObject` assets at runtime. Use instance state or a non-serialized runtime override with an explicit reset lifecycle.

## Implementation rules

- Do not use `goto`; prefer guard clauses and early returns over nested `if`/`else`.
- Prefer deletion over speculative code. Remove dead fields, callbacks, configuration, branches, and abstractions; add code only for a current requirement or enforced invariant.
- Prefer generic reusable helpers named for what they do, not caller-purpose helpers named after the first feature that needed them.
- Simulator and diagnostic tools act on the consumer's real instance. A throwaway service may preview UI, but it cannot claim to schedule, deliver, route, or mutate the running application's state.
- Private fields use `_camelCase`, including static fields. Never use `m_*` or `s_*`.
- Private methods use `PascalCase`; private constants use plain `PascalCase`, never underscore prefixes, `c_`, or screaming snake case.
- Use `nameof(T)` instead of string literals for paths, keys, or prefixes derived from a type name.
- Types that own Unity objects, native handles, callbacks, coroutines, or global subscriptions need idempotent teardown and consistent post-disposal behavior.
- Do not disable or release a shared global facility without exclusive ownership or reference-counted acquisition. Test concurrent owners when changing such lifecycle code.
- When renaming a captured loop variable, update every body reference and grep the complete method before considering the rename complete.

### Code comments

- Comments explain non-obvious rationale: trade-offs, invariants, ordering requirements not enforced by types, and external workarounds. Never narrate obvious control flow.
- Describe the code's durable state, not the edit history. Change narration belongs in the commit message.
- Prefer clearer names and structure over comments. One sentence is usually enough; multi-paragraph rationale belongs in `docs/` behind a short pointer.
- A comment on a private member is a last resort. Add one only when the name and body together still cannot convey the reason; do not replace removed private XML documentation with a narrating `//` comment.

### XML documentation

- Never add XML documentation to private members or private/nested-private types, constructors of any access, generated code, tests, or sample driver classes.
- Accessibility is effective, not merely declared. Members of an internal type are internal; members of a private nested type are private even when declared public or override.
- Document public, protected, and internal types and their non-private methods, properties, events, and fields.
- Put the documentation block above the full attribute run, never between an attribute and its declaration.
- Properties, events, and fields use a one-line summary only when the entire indented line fits within 120 columns; otherwise use a wrapped summary block.
- Public consumer-facing methods and types always use a multi-line summary block. Internal and Editor-only methods/types use a concise one-sentence summary, wrapped only when needed for the 120-column limit. Sample drivers are exempt; if a sample intentionally documents a reusable non-driver helper, use the same concise tier.
- Enum values use an inline `//` comment on the declaration line, not an XML summary above the value.
- Use `remarks` only for non-obvious durable behavior or invariants, not the current call graph.
- Use `param`, `returns`, `typeparam`, and `exception` on the consumer-facing contract: the interface declaration or a public type with no interface to inherit from. Do not add those tags to internal, Editor-only, or private implementation code; `paramref` inside a summary is fine.
- Use `inheritdoc` for interface implementations and overrides only after confirming the inherited declaration has documentation. A type implementing a documented interface may use a single-line `inheritdoc`.

### Member ordering

Omit categories that do not apply, but keep this order inside a type:

1. Public inner types.
2. Const fields.
3. Static fields.
4. `SerializeField` fields.
5. Public fields.
6. Private fields.
7. Properties.
8. Constructor.
9. Unity `MonoBehaviour` methods.
10. Methods by access.

Order methods by access as: public static, public override, public abstract, public, internal, protected, private. Keep internal methods in one contiguous block above private methods, including internal test seams.

### Editor UI

- New Editor windows, inspectors, and property drawers use UI Toolkit. Maintain existing IMGUI surfaces without converting unrelated code.
- In a namespace ending with `.Editor`, qualify the inspector base as `UnityEditor.Editor` to avoid resolving `Editor` as the namespace.
- `EditorWindow` scheduling goes through `rootVisualElement.schedule`; only `VisualElement` instances expose `schedule` directly.
- Keep one owner per pointer/touch interaction stream. Release custom pointer capture and reset state on Up, Cancel, owned CaptureOut, detach, disable, application pause, and focus loss.
- Buttons added to a `Foldout` toggle/header row must stop click propagation so their action does not also toggle the foldout.

## Documentation style

- The root `README.md` documents this host. Package `README.md`/`docs/` document consumer installation, usage, API, and samples. Package `AGENTS.md` files document contributor constraints.
- Do not declare another document authoritative unless synchronization is enforced. Prefer one owned rule or a generated/synchronized block.
- Keep package READMEs focused on adoption. Move deep API reference into package `docs/` when the README would otherwise grow beyond roughly 350 lines.
- Run `python3 Tools/lint-agent-guides.py` after changing any `AGENTS.md`.

## Releases

- Follow the package's existing unpublished changelog section. Do not bump `package.json` or add migration entries until an actual release is being cut.
- New changelog sections use `**New**:`, `**Changed**:`, `**Fixed**:`, and `**Docs**:` labels. Preserve historical sections and file formatting.
- Release notes describe consumer-visible outcomes, compatibility, dependencies, and migrations—not internal refactors, individual tests, or audit mechanics.

## Guide maintenance

- Keep rules stable, scoped, and actionable. Move architecture inventories to package docs and keep dated test/coverage evidence in existing test artifacts rather than `AGENTS.md`.
- A new nested `AGENTS.md` also needs the existing sibling `CLAUDE.md` wrapper pattern and Unity `.meta` files where applicable.
