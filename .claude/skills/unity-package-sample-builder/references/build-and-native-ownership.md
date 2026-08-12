# Sample Build and Native Ownership

Use this reference for a sample that prepares a player build, resolves scene identity, contributes temporary configuration, or needs Android/iOS declarations. It applies to one scene or a catalog-backed bundle in any UPM package.

## Choose the smallest scene-identity shape

### Single scene

Do not introduce a catalog when the sample only opens and plays one scene and has no automated build predicate. The scene asset itself is sufficient.

When automation must resolve that scene after import, store one serialized `SceneAsset` reference in a sample-owned editor-only `ScriptableObject`. Discover that typed asset by type, require an unambiguous result, and derive the current path with `AssetDatabase.GetAssetPath` at the point of use.

### Multiple scenes

Use one sample-owned typed `ScriptableObject` catalog under `Samples~/<Bundle>/Editor/`. Each serialized entry pairs the sample's stable logical key—page enum, feature id, or another package-specific identity—with a `SceneAsset`.

Keep a static facade only when it centralizes validation and access. It must not contain a second dictionary of GUIDs or paths.

Validate before use:

- exactly one imported catalog asset;
- the expected entry count when the bundle defines one;
- non-null scene references;
- unique logical keys and scene assets;
- required ordering or key coverage;
- a non-empty current path ending in `.unity` for every referenced scene.

Type discovery errors list every discovered asset path. Entry errors name the catalog, logical key/index, and failed reference.

## Treat serialized references as the source of truth

- Never hand-author a 32-character asset GUID or sample-relative `.unity` path in C# or shell lookup logic.
- Engine-managed `.meta` GUIDs and serialized YAML references remain expected metadata.
- Resolve current paths with `AssetDatabase.GetAssetPath` and derive diagnostic GUIDs from the resolved path only when reporting identity.
- Use the same validated resolver for navigation, build preparation, activation matching, and verification.
- Do not substitute filename search, labels, `Resources.Load`, `GlobalObjectId` strings, generated constants, or direct YAML parsing.

Static guards should reject prohibited literals, include must-flag and must-not-flag fixtures, and distinguish authored lookup strings from engine-managed metadata and documentation examples.

## Preflight before changing project state

Complete every applicable check before touching Build Settings, a Build Profile, persisted configuration, or generated native files:

1. Resolve and validate the single scene or catalog.
2. Resolve production configuration and reject ambiguity.
3. Validate explicitly enabled settings and external coordinates.
4. Evaluate the project's manual-management policy.
5. Compute the exact activation predicate and desired mutation set.

Missing optional production configuration is a no-op. A convenience singleton or transient default used by an Inspector is not authorization to mutate a player build.

If build preparation changes scenes, snapshot only the state it owns. Keep restoration scoped to that snapshot; do not make `Restore` a general project reset.

## Match builds exactly

When sample requirements activate from the enabled scene sequence, compare the full ordered sequence of resolved paths. Do not activate on partial membership, filename equality, unordered sets, or “contains all canonical scenes.” Disabled unrelated scenes may remain only when the package policy explicitly permits them.

For a single-scene sample, exact means that one resolved enabled scene and no additional enabled scene unless the documented contract says otherwise.

## Keep native generation package-owned

Production native integration belongs to the installed package because consumers need it without importing a sample. The package owns the Android manifest/Gradle and iOS plist/entitlement/PBX mutation pipeline.

A sample may contribute temporary declarative requirements through a package-owned extension point or scoped build context. It must not ship a second native postprocessor that edits the same generated artifacts.

The package boundary should:

- return false when neither a persisted configuration nor explicit context exists;
- reject duplicate persisted configurations with every asset path;
- clone persisted configuration before applying sample requirements;
- otherwise create a neutral transient configuration with every native feature disabled;
- never persist or dirty the temporary clone;
- validate malformed explicitly enabled rows before scanning or file access;
- treat scanner/config mismatches as advisory unless package policy says otherwise;
- treat manual native management as no validation and no mutation.

Push temporary context only after the exact sample build predicate matches. Declare processor and cleanup callback order explicitly, keep the context alive through every platform callback that consumes it, and clean it after success, failure, or cancellation.

## Mutate native artifacts semantically

Merge declarations by meaning rather than by raw text:

- Android permissions by permission name;
- manifest queries by semantic child identity;
- intent filters by scheme/host/path constraints;
- Maven dependencies by normalized coordinate;
- iOS URL schemes and localizations as sets;
- usage descriptions without replacing conflicting non-empty consumer text;
- entitlements and Associated Domains as set unions;
- PBX files, build settings, and registrations without duplicates.

Require an unambiguous target when mutation depends on a Unity activity, Gradle module, Xcode target, or entitlement path. Name every candidate path in ambiguity failures.

Reuse consumer-owned files and settings when valid. Create deterministic package-owned output only when no suitable consumer value exists. Save only changed files and emit one attributed summary naming the source configuration, changes, already-satisfied values, warnings, conflicts, and external dependencies.

## Build authoritative verification

Let shell scripts orchestrate; let Unity resolve Unity identities.

- Read a sample's source path and display name from its matching `package.json` `samples[]` entry.
- Have an Editor entry point resolve the validated scene identity and write a fresh artifact containing logical key, current asset path, and derived GUID.
- Delete or uniquely name the expected artifact before each run, then require it to be fresh and non-empty.
- Require unique, non-empty keys, paths, and GUIDs rather than accepting the verifier's verdict alone.
- Print editor version, source identity, inputs, artifact path, and byte/row counts.

Exercise the failure polarity:

1. Move/rename a referenced scene with `AssetDatabase.MoveAsset`; resolution must follow it without source edits.
2. Null a reference, duplicate a key, and duplicate the catalog separately; each must fail before project state changes.
3. Confirm missing production config makes no native changes.
4. Confirm manual management makes no native changes and any Continue/Cancel UX is respected.
5. Confirm exact sample builds receive temporary requirements and reordered/mixed builds do not.
6. Compare the persisted configuration bytes before and after the build.
7. Process identical native inputs twice and compare non-empty checksums for duplicate-free output.
8. Import and compile the actual sample in every supported editor stream.
9. Delete the imported sample and confirm its menus, callbacks, assemblies, and temporary state disappear while production tooling remains.

When compatibility with third-party native processors matters, inspect isolated final artifacts after all processors run. Attribute coexistence claims to those artifacts, not merely to the absence of exceptions.
