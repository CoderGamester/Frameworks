# UPM Sample Lifetime and Ownership

Use this reference whenever a task adds, merges, moves, or removes sample content or editor automation.

## Ownership questions

Answer these before implementation:

1. Must the behavior exist when the package is installed without its sample?
2. Must deleting the imported sample remove the behavior?
3. Does the code reference a sample scene, GUID, sample type, or sample-only asset?
4. Does it mutate production configuration or only prepare a demonstration build?
5. Which assembly owns the API, and which direction must the reference point?

Production runtime and build integration remain package-owned. Sample scene discovery, navigation bridges, simulator adapters, sample build menus, and temporary sample requirements are sample-owned.

## Merged sample bundles

One `package.json` sample entry may contain multiple independently openable scenes. Prefer one runtime asmdef and one Editor asmdef for shared player infrastructure unless a real dependency boundary requires more.

For a multi-scene player:

- Preserve existing scene names and GUIDs when possible.
- Put shared navigation/session behavior in a sample-internal `Shared/` area.
- Keep navigation outside page ScrollViews.
- Resolve scenes through serialized `SceneAsset` references rather than copied GUIDs or versioned import paths.
- Support playing each scene directly in the Editor.
- Define one canonical player scene order and validate every scene before changing Build Settings or a Build Profile.

For single-scene and catalog-backed player build ownership, including temporary native requirements, follow [build-and-native-ownership.md](build-and-native-ownership.md).

## Sample-scoped Editor automation

Editor code under `Samples~` compiles only after import. It must have an Editor-only asmdef and must not be referenced by the package Editor assembly.

Use these contracts:

- **Lifetime:** deleting the imported sample removes its menus, preprocessors, postprocessors, bridges, and adapters.
- **First import:** an `AssetPostprocessor` imported in the same batch cannot process that batch. Add a deferred domain-load safety net when automatic setup is required.
- **Decoupling:** use a package-owned extension contract or guarded menu invocation; never make the package depend on the optional sample assembly.
- **Idempotency:** derive desired state from current assets/configuration and skip work already satisfied.

## Build preparation

Distinguish build preparation from native production integration:

- Sample build preparation may select canonical scenes, snapshot/restore scene configuration, and contribute temporary requirements.
- Package production integration owns configuration and generated-project mutation required by consumers without a sample.
- Do not duplicate plist, entitlement, manifest, or Gradle ownership in both assemblies.
- Respect a project's manual-management escape hatch. Warn rather than silently overriding it.
- Temporary contexts must be released after success, failure, or cancellation and must not persist into project assets or `EditorPrefs`.

## Import and deletion acceptance

Verify the consumer lifecycle, not only the package source:

1. Import through Package Manager or copy to a clean scratch path under `Assets/`.
2. Wait for compilation and confirm both sample asmdefs loaded.
3. Open and play every supported scene.
4. Exercise navigation, content scrolling, and all enabled controls.
5. Run sample build preparation and restoration where applicable.
6. Delete the imported bundle.
7. Confirm no sample menu, callback, assembly, scene hook, or compile error remains.
8. Confirm package-owned production tools still exist.

Samples normally ship no tests. Package tests cover reusable package behavior; the sample is accepted as an imported interactive artifact.
