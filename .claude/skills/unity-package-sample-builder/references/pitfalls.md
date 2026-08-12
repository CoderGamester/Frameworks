# Unity Sample Pitfalls

Consult only the entries relevant to the current implementation or symptom.

## Imported assembly boundaries

`Samples~` is ignored by normal package compilation. Import the sample under `Assets/` to reveal missing asmdef references. References are not transitive; a sample touching a type surfaced by another assembly needs a direct reference to that assembly.

## Stale Editor assemblies

Editing a generator or sample Editor script on disk does not mean Unity compiled it. Force import, request compilation, wait until `IsCompiling` is false, and prove the new version produced a unique observable change.

## Input module without actions

Programmatically adding `InputSystemUIInputModule` without `AssignDefaultActions()` produces visible, interactable-looking buttons that receive no input and emit no error.

## Direct handler invocation

Calling `button.onClick.Invoke()` or a UI Toolkit callback proves handler behavior only. It bypasses raycasting, pointer capture, input modules, and click eligibility; never cite it as proof that a user can press the control.

## Scroll and button arbitration

Do not stack a custom gesture controller over a ScrollView based on symptoms alone. First identify which element captures the pointer and which terminal event fails. A press should remain eligible for click until movement exceeds a drag threshold; a committed drag cancels the click and belongs to scrolling. Pressed visuals must clear on pointer up, cancel, capture loss, disable, and navigation.

## Custom Editor recursion

A `[CustomEditor(..., editorForChildClasses: true)]` that constructs an `InspectorElement` from the same `serializedObject` can recurse through the custom editor and crash Unity. Render properties manually and bind the root instead.

## ScriptableObject metadata

If a hand-authored ScriptableObject asset imports before its script compiles, Unity may rewrite `mainObjectFileID` incorrectly. Reimport after compilation and preserve the canonical `11400000` main object file ID when the asset YAML uses that anchor.

## Canvas and camera hierarchy

A camera rendering a Screen Space - Camera canvas must not be parented under that canvas. Unity drives the canvas transform, which moves/scales the camera onto the canvas plane. URP overlay cameras in a camera stack must also remain active and enabled; stack membership alone does not make them render.

## World-space spawning from a canvas

Do not use a screen-space canvas transform position as a world-space spawn position. Use an explicit world position derived from the camera. Despawn moving sample objects that leave the visible viewport.

## Pipeline-neutral materials

When a pipeline-neutral sample tints runtime materials, set `_BaseColor` when present and `_Color` when present. Do not add a URP dependency solely to color a primitive.

## Routine sample logging

Samples should surface normal actions and state through their visible UI. Temporary diagnostic logs must be removed before handoff; retain Console output only for actionable warnings and failures.
