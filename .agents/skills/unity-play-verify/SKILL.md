---
name: unity-play-verify
description: Verify visible and interactive Unity behavior by driving the running Editor and observing the result instead of inferring it from compilation or tests. Use for rendering, cameras, UI layout, UI Toolkit/uGUI controls, scrolling, pointer input, shaders, animation, Device Simulator behavior, or any change whose success must be seen or interacted with. Drives play mode through Unity MCP or an explicit UI-control fallback, captures the Game view, and distinguishes handler invocation from real user input. Not for pure logic changes a unit test settles and not a substitute for the test suites.
---

# Unity play-mode verification

A compiling project with a green suite tells you nothing about whether anything appeared on screen.
This skill closes that gap by running the game and looking.

Recorded instance that motivates it: `UiCameraStackFeature` shipped having **never rendered anything**,
past 284 passing PlayMode tests, because the tests asserted the camera was in URP's stack and URP
skips stacked cameras that are disabled. One screenshot found it. Three more bugs — dead buttons, an
opaque white panel over the log text, and text overlapping its own button — surfaced in the same pass,
none of which produced a console message.

## Prerequisite

`com.unity.ai.assistant` in `Packages/manifest.json` provides the MCP tool surface
(`Unity_ManageEditor`, `Unity_RunCommand`, `Unity_ReadConsole`, `Unity_ManageScene`,
`Unity_ManageMenuItem`, `Unity_Camera_Capture`). **The Editor must be OPEN** — the opposite of the
batchmode requirement, and it means the project lock blocks `unity test` while you work. Plan to do
all visual verification first, then close the Editor and run the suites.

Resolve the Editor by project path, not by macOS bundle identifier or window title alone. Multiple
Unity projects and editor versions can be open under the same application identity. Match the
process command line to the project's `Temp/UnityLockfile` before focusing, driving, quitting, or
terminating an Editor. Never disturb an Editor owned by another project; use an isolated host when
the intended window cannot be targeted safely.

## The loop

### 1. Confirm the Editor is idle

```
Unity_ManageEditor { Action: "GetState" }
```

Check `IsCompiling: false` and `IsUpdating: false`. Acting while compiling silently uses the old
assemblies.

### 2. After ANY script edit, force a recompile before relying on it

Editing a file on disk does not recompile it. Invoking a menu item or entering play mode straight
after a `Write` runs the **stale assembly** — observed twice in one session, producing confidently
wrong generated assets with no error.

```csharp
AssetDatabase.ImportAsset("<path/to/edited.cs>", ImportAssetOptions.ForceUpdate);
UnityEditor.Compilation.CompilationPipeline.RequestScriptCompilation();
```

Then re-check `GetState` for `IsCompiling: false`, and prove the new code ran by grepping the output
for something only the new version produces. "The menu item returned success" is not evidence.

### 3. Load the scene and enter play mode

```
Unity_ManageScene  { Action: "Load", Name: "<Scene>", Path: "<folder>" }
Unity_ManageEditor { Action: "Play", WaitForCompletion: true }
```

### 4. Drive the UI at the correct evidence level

For UI input, read [references/ui-interaction.md](references/ui-interaction.md) and run its interaction matrix.

For Unity 6 UI Toolkit samples that rely on InputForUI, also read [references/inputforui.md](references/inputforui.md). Prove provider identity, absence of a sample-owned uGUI EventSystem, a real foreground pointer action, and an observable result; structural UI queries or a synthetic injector that emitted zero pointer events are failures, not partial passes.

Prefer a Unity MCP pointer/click/drag surface when available. If the current Unity MCP does not expose real pointer input, use the approved local computer-use capability against the Game or Device Simulator view. Record which path was used.

Direct handler invocation is a lower evidence level:

```csharp
foreach (var b in Object.FindObjectsByType<Button>(FindObjectsSortMode.None))
    if (b.gameObject.name == "MyButton") b.onClick.Invoke();
```

This bypasses raycasting, UI Toolkit propagation, pointer capture, the input module, and click eligibility. It proves only that the mapped handler works. Do not report a control as clickable unless a real pointer interaction reached it. When no real-input tool is available, report that limitation explicitly.

For uGUI, also confirm `EventSystem.current.currentInputModule` exists and New-Input-only modules have actions assigned. For UI Toolkit, inspect the pointer event/capture lifecycle described in the interaction reference.

### 5. Capture — and use the right capture

```csharp
ScreenCapture.CaptureScreenshot("<abs path>/shot.png");
```

**Use `ScreenCapture`, not `Unity_Camera_Capture`, whenever a renderer feature is involved.**
`Unity_Camera_Capture` renders the camera into a RenderTexture, and any pass that skips
render-texture-target cameras (a very common guard — blur, backdrop and screen-space effects all do
it) will be absent from the image. You would photograph the exact absence you are trying to disprove.
`Unity_Camera_Capture` is still the right tool for framing and placement questions.

`CaptureScreenshot` completes at end of frame, so request it in one `Unity_RunCommand` and read the
file afterwards, not in the same call.

UI Toolkit overlays can be absent from a framebuffer screenshot even when a populated visual tree
exists. If the capture contains only the camera clear colour, capture the actual Game view through
the Editor or use a target-device screenshot. Do not treat UI-tree geometry as a substitute for the
missing pixels.

### 6. Read the image and judge it

Read the PNG directly. Compare against a baseline capture of the same scene with the feature off —
"is this blurred" is far easier as a two-image comparison than in the absolute.

A non-empty PNG is not visual evidence by itself. Reject a capture that is uniform or nearly
uniform, missing expected task-specific landmarks, stale, from the wrong scene/tab/orientation, or
showing an Editor panel instead of the target Game view. Byte size, valid dimensions, pixel variance,
and a harness-reported `PASS` are supporting checks; direct image inspection or an independent
landmark check is still required. A high-entropy image of the wrong window is also a failure.

Persistent UI shells keep hidden pages in the same visual tree. Query the selected visible page root
before reading titles, bounds, or controls; a global `Query<Label>().First()` can return a valid label
from an inactive page. Confirm the page and relevant ancestors are displayed and exactly one
destination is selected.

For mobile UI, capture at least one notched iOS and Android profile where available. Check portrait and landscape when the layout claims to support both. A screenshot proves appearance only; pair it with real click and drag observations for interactive work.

Store the observation in a run-specific artifact set that names the editor, code identity, scene, interaction driver, and output byte counts. Do not replace an earlier result in place or silently reuse a file from another editor/run.
Require the behavior artifact itself to state `PASS`; the existence of the report or screenshot is
never a pass condition. Preserve invalid visual attempts under their original run identity.

### 7. Check the console separately

```
Unity_ReadConsole { Action: "Clear" }   // before the action
Unity_ReadConsole { Action: "Get", Types: ["Error", "Warning"] }
```

Clearing first is what makes "0 entries" mean anything. To attribute a warning, clear, reproduce with
the feature OFF, then ON — that is how the two Metal `memoryless` warnings were pinned to the blur
pass rather than guessed at.

## `Unity_RunCommand` constraints

Each is a real error encountered, not a caution:

- The class **must** be `internal class CommandScript : IRunCommand`. Other names fail at runtime.
- Your code is wrapped in `namespace Unity.AI.Assistant.Agent.Dynamic.Extension.Editor`, so
  unqualified type names can resolve to that namespace instead of yours. `CompilationPipeline`
  becomes `Unity.CompilationPipeline` and fails — write
  `UnityEditor.Compilation.CompilationPipeline`.
- **`System.Reflection` is blocked.** Read state off the scene (a status label, a component field)
  rather than reflecting into internals.
- It **cannot reference package assemblies**. `using GameLovers.UiService.Rendering;` fails with
  `CS0234`. Assert against what is observable in the scene instead.
- `Execute` is synchronous — it cannot wait frames. Split "act" and "capture/observe" across separate
  calls so frames elapse in between.

## Batchmode variant, when the Editor cannot be open

Batchmode renders only if `-nographics` is **dropped**. A `[UnityTest]` can then enter play mode,
`yield return null` to let frames render, capture, and write PNGs — which turns a visual check into a
regression guard rather than a one-off. Still subject to the same `ScreenCapture`-vs-RenderTexture
caveat above.

## Do not stop at the first green frame

Every one of these was found *after* the feature "worked":

| Symptom | Cause | Console said |
|---|---|---|
| Nothing renders | stacked overlay camera left disabled | nothing |
| Nothing renders | camera parented under the canvas it renders | nothing |
| Buttons dead | input module added without default actions | nothing |
| White block over text | default-white `Image` on a ScrollRect viewport | nothing |
| Text overlapping its button | fixed `LayoutElement.minHeight` clamping wrapped text | nothing |

Exercise every control, every open/close cycle, and at least one negative case (remove the required
setup and confirm the error path fires). Then hand the user only the judgement calls a capture cannot
settle — "does this look good" — never "does it work".
