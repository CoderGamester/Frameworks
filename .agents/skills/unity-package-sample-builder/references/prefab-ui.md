# Authoring uGUI/TMP Sample Prefabs

Use this reference only when a sample owns uGUI/TMP runtime-built UI or needs a generated prefab/scene hierarchy. UI Toolkit samples should follow their package's authored UXML/USS patterns instead.

## Driver shape

- Replace runtime `BuildUI()` helpers with serialized references.
- Group related references with `[Header]` attributes.
- Wire actions once during initialization through a small null-safe helper.
- Keep action methods stable when existing prefab events or documentation rely on them.
- Remove obsolete runtime hierarchy helpers after the authored asset is verified.

## Input-module portability

An imported sample must work with the consumer project's Active Input Handling setting.

- Under the new Input System, ensure an `InputSystemUIInputModule` exists and call `AssignDefaultActions()` when adding it programmatically.
- Remove a legacy `StandaloneInputModule` before its first update in a New-only project.
- Under the legacy path, ensure one `StandaloneInputModule` exists.
- Verify the active module in Play Mode; a visible `interactable` button does not prove input actions are assigned.

## One-shot authoring utility

When programmatic authoring is appropriate, place the temporary generator under the host project's `Assets/Editor/Tools/`, not inside the shipped sample.

The generator should:

1. Build the hierarchy with layout components and TMP text.
2. Assign serialized references through `SerializedObject`.
3. Save the prefab through `PrefabUtility`.
4. Rewire and save the scene.
5. Mirror prefab, scene, and `.meta` files back to `Samples~` while preserving GUIDs.

After editing the generator, force import and script compilation before invoking it. Prove the new assembly ran by checking an output field unique to the new version.

Delete the temporary generator and empty host `Editor/Tools` folders after the authored assets are validated.

## Scrollable logs

When appending to a `ScrollRect` log, capture whether the user was already at the bottom before changing content. Auto-scroll only when they were at the bottom; preserve their position while they read earlier entries.

## Visual acceptance

Use `unity-play-verify`. Inspect at minimum:

- Text wrapping and clipping.
- Button label readability.
- Viewport backgrounds and masks.
- Layout minimum heights.
- Input module and actual pointer clicks.
- Content scrolling without relying only on the scrollbar.
