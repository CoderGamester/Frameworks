# Consumer-time Sample Automation

Use this reference for Addressables groups, generated registries, imported content normalization, or other setup that must run on the consumer's machine after a sample import.

## Assembly and trigger shape

Ship the automation under `Samples~/<Sample>/Editor/` with an Editor-only asmdef. Route all triggers through one idempotent setup method:

- A manual menu item for recovery and diagnosis.
- `AssetPostprocessor.OnPostprocessAllAssets` for later asset changes.
- A deferred `[InitializeOnLoadMethod]` safety net for the sample's first import.

Both automatic paths must defer mutation through `EditorApplication.delayCall`.

## Self-location

Locate the imported sample root from the automation type's `MonoScript` or stable asset GUID. Never hardcode the Package Manager destination version because Unity imports to `Assets/Samples/<display name>/<version>/...`.

## Idempotent setup pipeline

For Addressables/config registry samples:

1. Exit silently when required content or assets are absent.
2. Normalize only assets the sample owns.
3. Create or reuse one dedicated sample Addressables group.
4. Create or move only the sample's entries.
5. Assign deterministic addresses.
6. Fill empty or canonical config mappings through `SerializedObject`.
7. Preserve any row the user has intentionally mapped to a different asset.
8. Save only when state changed.

Do not write into the user's default Addressables group. Do not overwrite user-owned mappings. Make group deletion a clear manual undo path.

## Package-to-sample affordances

The package Editor assembly cannot reference an optional sample Editor assembly. If a package inspector exposes a sample-specific action:

- Show it only when the inspected asset path identifies that imported sample.
- Invoke a sample menu via `EditorApplication.ExecuteMenuItem` or use a package-owned generic extension contract.
- Handle the missing sample/menu without creating a compile dependency.

## Documentation and acceptance

Document the automatic flow, manual fallback, user-content replacement behavior, and undo. Verify first import in a clean consumer host; reloading an already-configured development project does not exercise the chicken-and-egg path.
