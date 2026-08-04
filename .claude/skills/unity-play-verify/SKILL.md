---
name: unity-play-verify
description: Verify Unity runtime behaviour by driving the running Editor and LOOKING at the result, instead of inferring it from a green test run. Use when a change has visible output — rendering, renderer features, UI layout, camera setup, shaders, animation — or when tests pass but you have not seen the thing work. Drives play mode over the Unity MCP, invokes UI, captures the Game view, and reads the image back. NOT for pure logic changes a unit test settles, and not a substitute for running the test suites.
---

# Unity play-mode verification

A compiling project with a green suite tells you nothing about whether anything appeared on screen.
This skill closes that gap by running the game and looking.

Recorded instance that motivates it: `UiCameraStackFeature` shipped having **never rendered anything**,
past 284 passing PlayMode tests, because the tests asserted the camera was in URP's stack and URP
skips stacked cameras that are disabled. One screenshot found it. Three more bugs — dead buttons, an
opaque white panel over the log text, and text overlapping its own button — surfaced in the same pass,
none of which produced a console message.

## When to use

Use when the change has visible output and you have not seen it:

- renderer features, render passes, shaders, post-processing
- camera setup: stacking, culling masks, render modes, targets
- UI layout, prefab-generated UI, canvas render modes
- anything where "it works" means "it looks right"

Do NOT use for logic a unit test settles, and never as a replacement for the suites — see
`AGENTS.md` §2.5. This verifies *behaviour*; the suites guard *regression*.

## Prerequisite

`com.unity.ai.assistant` in `Packages/manifest.json` provides the MCP tool surface
(`Unity_ManageEditor`, `Unity_RunCommand`, `Unity_ReadConsole`, `Unity_ManageScene`,
`Unity_ManageMenuItem`, `Unity_Camera_Capture`). **The Editor must be OPEN** — the opposite of the
batchmode requirement, and it means the project lock blocks `unity test` while you work. Plan to do
all visual verification first, then close the Editor and run the suites.

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

### 4. Drive the UI

There is no click tool. Invoke the handler directly:

```csharp
foreach (var b in Object.FindObjectsByType<Button>(FindObjectsSortMode.None))
    if (b.gameObject.name == "MyButton") b.onClick.Invoke();
```

This bypasses raycasting and the input module, so it does not prove the button is *clickable* — only
that its handler works. To check input actually reaches UI, assert
`EventSystem.current.currentInputModule` is present and, on New-Input-only projects, that the module
has actions assigned (see `unity-package-sample-builder` Step 2).

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

### 6. Read the image and judge it

Read the PNG directly. Compare against a baseline capture of the same scene with the feature off —
"is this blurred" is far easier as a two-image comparison than in the absolute.

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
