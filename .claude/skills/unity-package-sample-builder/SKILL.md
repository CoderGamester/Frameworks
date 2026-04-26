---
name: unity-package-sample-builder
description: Author or improve a Unity Package Manager sample under `Packages/<pkg>/Samples~/<sample>/`. Covers two tracks that often run sequentially. **Authoring-time UI track** — refactor the runtime driver to use `[SerializeField]` references, write a one-shot `Assets/Editor/Tools/Generate*Prefabs.cs` utility (deleted after validation) that produces the Canvas/Buttons/TMP prefab + rewires the scene + mirrors back into `Samples~/`, plus an input-module swap so samples are portable across Active Input Handling settings. **Consumer-time content automation track** — for samples that require runtime asset wiring on the consumer's machine (Addressables groups, populated `AssetConfigsScriptableObject<TId, TAsset>` rows), ship a sample-scoped editor automation under `Samples~/<sample>/Editor/` with its own `.asmdef`, an `AssetPostprocessor` + `[InitializeOnLoadMethod]` safety net + menu + path-guarded inspector button, all idempotent and decoupled from the package's main editor assembly. Use when adding a new sample, refactoring an existing runtime-built UI to a prefab, or making an existing manual-setup sample zero-click on import.
---

# Unity Package Sample — Builder

Two-track skill for Unity Package Manager samples shipped under `Packages/<pkg>/Samples~/<sample>/`:

- **Track A — Authoring-time UI** (Steps 1–6): refactor the driver, generate the prefab via a one-shot editor utility, mirror back to `Samples~/`, validate, delete the utility.
- **Track B — Consumer-time content automation** (Step 7): ship sample-scoped editor automation that auto-marks sample assets Addressable and wires the sample's `AssetConfigsScriptableObject` instance on the consumer's first import.

The tracks are independent — run only the one(s) relevant to the current task. When both apply for a new sample, do Track A first (so the prefab + scene exist) then Track B (so runtime-content registration has something to register against).

## When to Use

Trigger this skill when the user asks any of:
- "Add a sample to `<package>` that demonstrates X." (both tracks may apply)
- "Build the UI Canvas in this sample as a prefab instead of generating from a script at runtime." (Track A)
- "Make the sample press-Play-and-it-works without per-import setup." (both tracks)
- "Auto-mark this sample's sprites/prefabs/scenes as Addressable on import." (Track B)
- "Eliminate the manual Addressables setup steps from the sample's README." (Track B)

Do NOT trigger for:
- Editor-only tools (use UIToolkit `EditorWindow` patterns instead).
- Production game UIs (samples are demo-only).
- Sample logic refactors that don't touch the UI hierarchy or runtime asset registration.

## Track A — Authoring-time UI (Steps 1–6)

### Step 1 — Refactor the runtime driver

The driver (e.g. `<Sample>UI.cs`) before this step usually owns a `BuildUI()` method that creates Canvas + sections + buttons + texts at runtime. Replace that with `[SerializeField]` references plus `Awake` wiring.

For each interactive element on the prefab, add a `[SerializeField]` field on the driver:

```csharp
[Header("Tuning")]
[SerializeField] private float _someSliderDefault = 60f;

[Header("Status panes")]
[SerializeField] private TMPro.TMP_Text _log;
[SerializeField] private TMPro.TMP_Text _liveStatus;
[SerializeField] private UnityEngine.UI.ScrollRect _logScrollRect;

[Header("Section A buttons")]
[SerializeField] private UnityEngine.UI.Button _doThingButton;
[SerializeField] private UnityEngine.UI.Button _doOtherButton;
// ... one [SerializeField] Button per action ...
```

Group buttons under `[Header(...)]` attributes by service / section so the prefab inspector reads naturally. In `Awake`, call a small `WireButton(button, action)` helper for each:

```csharp
private void Awake()
{
    WireButton(_doThingButton,  Section_DoThing);
    WireButton(_doOtherButton,  Section_DoOther);
    EnsureInputModuleOnEventSystem();
}

private static void WireButton(Button button, UnityEngine.Events.UnityAction action)
{
    if (button != null) button.onClick.AddListener(action);
}
```

Remove every helper that no longer applies: `BuildUI`, `AddSection`, `AddButton`, `AddText`, `EnsureEventSystem`, `SetMinHeight`, `LegacyFont` accessor, etc. Keep the public `Section_*` action methods unchanged — those are the prefab's onClick targets.

### Step 2 — Add input-module portability

Sample drivers that include their own `EventSystem` in the scene must adapt the input module to the consumer project's Active Input Handling, otherwise New-only projects throw `InvalidOperationException` on `UnityEngine.Input.mousePosition`:

```csharp
private static void EnsureInputModuleOnEventSystem()
{
    var es = FindAnyObjectByType<UnityEngine.EventSystems.EventSystem>();
    if (es == null) return;
    var go = es.gameObject;
#if ENABLE_INPUT_SYSTEM
    if (go.GetComponent<UnityEngine.InputSystem.UI.InputSystemUIInputModule>() != null) return;
    var legacy = go.GetComponent<UnityEngine.EventSystems.StandaloneInputModule>();
    if (legacy != null) DestroyImmediate(legacy);
    go.AddComponent<UnityEngine.InputSystem.UI.InputSystemUIInputModule>();
#else
    if (go.GetComponent<UnityEngine.EventSystems.StandaloneInputModule>() == null)
        go.AddComponent<UnityEngine.EventSystems.StandaloneInputModule>();
#endif
}
```

Use `DestroyImmediate` (not `Destroy`) so the swap happens before `EventSystem.Update` first ticks the legacy module — otherwise one frame of `Input.mousePosition` exception fires before the swap takes effect.

### Step 3 — Auto-scroll for log panes that preserves user drag

Whenever the driver appends to a `_log` TMP_Text contained in a `_logScrollRect`, snapshot the scroll position BEFORE buffer mutation and only auto-scroll if the user was already at the bottom:

```csharp
private void Append(string line)
{
    if (_log == null) return;
    var wasAtBottom = _logScrollRect == null || _logScrollRect.verticalNormalizedPosition < 0.05f;
    // ...mutate _log.text...
    if (_logScrollRect != null && wasAtBottom)
    {
        Canvas.ForceUpdateCanvases();
        _logScrollRect.verticalNormalizedPosition = 0f;
    }
}
```

Standard chat-window semantics: pin to bottom on append unless the user has dragged up to read history.

### Step 4 — Write the one-shot editor utility

Path: `Assets/Editor/Tools/Generate<Sample>Prefabs.cs` (host-project Editor folder). One menu item per sample:

```csharp
[MenuItem("Tools/<TeamName>/[DEV] Generate <Sample>UI Prefab")]
public static void GenerateSamplePrefab() { /* ... */ }
```

Each menu item does FIVE things in order:

1. **Build the hierarchy programmatically** — `new GameObject("<Sample>Canvas", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster), typeof(<DriverComponent>))` as the root. Add columns / rows / sections via child GameObjects with `VerticalLayoutGroup` / `HorizontalLayoutGroup`. Use `TextMeshProUGUI` for text (not legacy `Text`) and a helper `AddScrollableTextPane` for log/status panes (RectTransform + Image bg + ScrollRect → Viewport with RectMask2D → Content with `TextMeshProUGUI` + `ContentSizeFitter`).

2. **Wire `[SerializeField]` references via `SerializedObject`**:

   ```csharp
   var so = new SerializedObject(refs.Driver);
   so.FindProperty("_log").objectReferenceValue = refs.Log;
   so.FindProperty("_logScrollRect").objectReferenceValue = refs.LogScrollRect;
   // ... one entry per [SerializeField] on the driver ...
   so.ApplyModifiedPropertiesWithoutUndo();
   ```

3. **Save as prefab** — `PrefabUtility.SaveAsPrefabAsset(canvasGo, "Assets/Samples/<pkg>/<version>/<sample>/<Sample>UI.prefab", out var success)`. Then `Object.DestroyImmediate(canvasGo)` and `AssetDatabase.SaveAssets() + AssetDatabase.Refresh()`.

4. **Mirror prefab + meta back to package source** — `PrefabUtility` cannot write outside `Assets/`, so use `System.IO.File.Copy` to push to `Packages/<pkg>/Samples~/<sample>/<Sample>UI.prefab` plus its `.meta`. Helper:

   ```csharp
   private static void MirrorToPackageSource(string assetPath, string packagePath)
   {
       var dir = Path.GetDirectoryName(packagePath);
       if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
       File.Copy(assetPath, packagePath, overwrite: true);
       var assetMeta = assetPath + ".meta";
       if (File.Exists(assetMeta)) File.Copy(assetMeta, packagePath + ".meta", overwrite: true);
   }
   ```

5. **Rewire the scene** to instance the prefab (instead of having the driver attached to a scene-root Bootstrap GO):

   ```csharp
   var scene = EditorSceneManager.OpenScene("<assets-path>/<sample>/<Sample>.unity", OpenSceneMode.Single);
   foreach (var rootGo in scene.GetRootGameObjects())
   {
       if (rootGo.GetComponent<Camera>() != null) continue; // keep main camera
       Object.DestroyImmediate(rootGo);
   }
   var es = new GameObject("EventSystem", typeof(EventSystem));
   UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(es, scene);
   var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
   instance.name = "<Sample>Canvas";
   EditorSceneManager.MarkSceneDirty(scene);
   EditorSceneManager.SaveScene(scene);
   MirrorToPackageSource(scenePath, samplesScenePath);
   ```

   Don't add a `BaseInputModule` to the EventSystem here — the driver's `EnsureInputModuleOnEventSystem` adds the right one at runtime.

### Step 5 — Halt for user, then validate

Hand off:
> Run **Tools / <TeamName> / [DEV] Generate <Sample>UI Prefab**. Confirm two log lines: prefab generated + scene rewired. Open the scene, press Play, exercise a few buttons.

Wait for the user's confirmation. If they report errors, iterate on the driver and/or editor utility.

### Step 6 — Cleanup after validation

When the user confirms both samples work:
- `Delete Assets/Editor/Tools/Generate<Sample>Prefabs.cs` and its `.meta`.
- Remove `Assets/Editor/Tools/` directory and its `.meta` (likely empty after deletion).
- Remove `Assets/Editor/` directory and its `.meta` if it became empty too.
- Reconcile the mirrors — `diff -q` every file in `Assets/Samples/<pkg>/<version>/<sample>/` against `Packages/<pkg>/Samples~/<sample>/`. If the user pressed Play after the menu ran, the `.unity` may be 10× larger in `Assets/Samples/` (Unity expanded the prefab-instance YAML on save). That's fine — mirror Assets/Samples → Samples~/ once more for the final source-of-truth.

## Track B — Consumer-time content automation (Step 7)

Run this track when the sample requires runtime asset wiring on the consumer's machine — typically when the sample uses an `AssetConfigsScriptableObject<TId, TAsset>` registry that needs Addressable entries pointing at sample assets. The goal is **zero-click on first import**: the user imports the sample, presses Play, and it works.

The sample-scoped editor automation must follow the three contracts from `Frameworks/AGENTS.md` §2 *Sample-scoped editor automation*: lifetime (lives inside `Samples~/<Sample>/Editor/` so it's removed with the sample), trigger redundancy (post-processor + `[InitializeOnLoadMethod]` safety net for the UPM first-import chicken-and-egg), and cross-assembly decoupling (no compile-time reference from the package's main editor; use `EditorApplication.ExecuteMenuItem` instead).

### Step 7 — Ship `Samples~/<Sample>/Editor/<Sample>SampleSetup.cs`

#### 7.1 Folder layout

```
Samples~/<Sample>/
  <Sample>.unity
  <Sample>UI.prefab
  <Driver>.cs                                          ← from Track A
  <Configs>.cs                                         ← AssetConfigsScriptableObject<TId, TAsset> subclass
  <Configs>.asset                                      ← shipped empty (auto-filled on import)
  <Id>.cs                                              ← TId enum (Hero/Coin/Enemy etc.)
  <Content>/                                           ← e.g. Sprites/, Prefabs/, Scenes/ — the assets the automation marks Addressable
    <Canonical1>.<ext>                                 ← shipped placeholders, names matching TId values
    <Canonical2>.<ext>
    <Canonical3>.<ext>
  Editor/
    <Sample>SampleSetup.cs                             ← Static class + nested AssetPostprocessor
    <Sample>SampleSetup.cs.meta                        ← deterministic GUID, hand-authored
    GameLovers.<Pkg>.Samples.<Sample>.Editor.asmdef    ← references package runtime + Addressables
    GameLovers.<Pkg>.Samples.<Sample>.Editor.asmdef.meta
```

Ship the placeholder content files with **canonical names** (matching the `TId` enum values, case-insensitive) so first import is a no-op for the rename pipeline. Names can be anything for user-replaced content — the rename pipeline normalises them.

#### 7.2 The `.asmdef`

```json
{
  "name": "GameLovers.<Pkg>.Samples.<Sample>.Editor",
  "rootNamespace": "GameLovers.<Pkg>.Samples.<Sample>.Editor",
  "references": [
    "GameLovers.<Pkg>",
    "GUID:9e24947de15b9834991c9d8411ea37cf",
    "GUID:69448af7b92c7f342b298e06a37122aa",
    "GUID:84651a3751eca9349aac36a66bba901b"
  ],
  "includePlatforms": ["Editor"],
  "excludePlatforms": [],
  "allowUnsafeCode": false,
  "overrideReferences": false,
  "precompiledReferences": [],
  "autoReferenced": true,
  "defineConstraints": [],
  "versionDefines": [],
  "noEngineReferences": false
}
```

The three GUIDs are stable across Addressables 1.x → 2.x: `9e24947de15b9834991c9d8411ea37cf` = `Unity.Addressables` (Runtime), `69448af7b92c7f342b298e06a37122aa` = `Unity.Addressables.Editor`, `84651a3751eca9349aac36a66bba901b` = `Unity.ResourceManager`. Reference Addressables by GUID, not by name, so the `.asmdef` survives Addressables version bumps in the consumer project.

#### 7.3 The setup script shape

```csharp
namespace GameLovers.<Pkg>.Samples.<Sample>.Editor
{
    public static class <Sample>SampleSetup
    {
        public const string GroupName = "GameLovers<Pkg>Samples_<Sample>";
        private const string ContentSubfolder = "<Content>";  // e.g. "Sprites"
        private const string ConfigsFileName = "<Configs>.asset";
        private static readonly string[] CanonicalNames = { "<Canonical1>", "<Canonical2>", "<Canonical3>" };

        [MenuItem("Tools/<TeamName>/Samples/<Sample>/Refresh Addressables")]
        public static void MenuRefresh() => RunSetup(silent: false);

        internal static void RunSilent() => RunSetup(silent: true);

        [InitializeOnLoadMethod]
        private static void OnDomainReload() => EditorApplication.delayCall += RunSilent;

        private static void RunSetup(bool silent) { /* see 7.4 */ }
    }

    internal sealed class <Sample>SampleAssetPostprocessor : AssetPostprocessor
    {
        private const string MarkerSegment = "/<Sample>/<Content>/";

        private static void OnPostprocessAllAssets(string[] imported, string[] _, string[] __, string[] ___)
        {
            foreach (var p in imported)
            {
                if (p.IndexOf(MarkerSegment, StringComparison.Ordinal) >= 0)
                {
                    EditorApplication.delayCall += <Sample>SampleSetup.RunSilent;
                    return;
                }
            }
        }
    }
}
```

Three triggers, all routing through `RunSetup(silent: true)` except the menu (silent: false): `OnPostprocessAllAssets` handles asset drops; `[InitializeOnLoadMethod]` is the chicken-and-egg safety net (post-processor compiles AFTER its own first-import batch); the menu is the manual escape hatch. **All three defer to `EditorApplication.delayCall`** because asset modification is unsafe during `OnPostprocessAllAssets` itself and during the InitializeOnLoad phase.

#### 7.4 The `RunSetup` pipeline

Six stages, in order:

**1. Self-locate the sample root** via `MonoScript`:

```csharp
var guids = AssetDatabase.FindAssets($"t:MonoScript {nameof(<Sample>SampleSetup)}");
foreach (var guid in guids)
{
    var path = AssetDatabase.GUIDToAssetPath(guid);
    var script = AssetDatabase.LoadAssetAtPath<MonoScript>(path);
    if (script != null && script.GetClass() == typeof(<Sample>SampleSetup))
    {
        // path = ".../<Sample>/Editor/<Sample>SampleSetup.cs"
        var sampleRoot = Path.GetDirectoryName(Path.GetDirectoryName(path))?.Replace('\\', '/');
        // ...
    }
}
```

This makes the script work regardless of which `<version>` folder UPM extracted to.

**2. Bail-out checks** (silent path returns without logging):
- `AssetDatabase.IsValidFolder("<sampleRoot>/<ContentSubfolder>")` → if false, the user hasn't dropped content yet.
- `AssetDatabase.FindAssets("t:Sprite", new[] { contentDir }).Length == 0` → no content yet.
- `<Configs>.asset` not found at `<sampleRoot>/<ConfigsFileName>` → wrong folder shape.

**3. Three-pass canonical rename** (between `AssetDatabase.StartAssetEditing` / `StopAssetEditing`):

```csharp
// Pass 1: exact match — already canonical, skip.
// Pass 2: substring match — filename contains a canonical name (case-insensitive)
//         e.g. "MyHeroIcon.png" → renamed to "Hero".
// Pass 3: alphabetical fallback — sort remaining files, assign to remaining slots in order.
```

Use `AssetDatabase.RenameAsset(path, newName)` (newName WITHOUT extension; returns empty string on success). After renames, call `AssetDatabase.Refresh()` and re-fetch the GUID list.

**4. Get-or-create the Addressables group**:

```csharp
var settings = AddressableAssetSettingsDefaultObject.GetSettings(create: true);
var group = settings.FindGroup(GroupName) ?? settings.CreateGroup(
    GroupName,
    setAsDefaultGroup: false,
    readOnly: false,
    postEvent: false,
    schemasToCopy: null,
    typeof(BundledAssetGroupSchema), typeof(ContentUpdateGroupSchema));
```

Use a dedicated group name `<Pkg>Samples_<Sample>` (or similar) — never write into the user's default group or any other user-defined group. Group deletion is the user's "undo".

**5. Mark each content asset Addressable**:

```csharp
var entry = settings.CreateOrMoveEntry(guid, group, readOnly: false, postEvent: false);
if (entry != null)
{
    var desiredAddress = name.ToLowerInvariant();
    if (entry.address != desiredAddress)
        entry.SetAddress(desiredAddress, postEvent: false);
}
```

**6. Wire `<Configs>.asset` rows via `SerializedObject`** — find or insert a row per `TId` enum value, set `Pair.Key` to the enum value as `intValue`, set `Pair.Value.m_AssetGUID` to the asset GUID. **CRITICAL: respect existing user mappings**:

```csharp
var existing = guidProp.stringValue;
if (!string.IsNullOrEmpty(existing) && existing != spriteGuid)
{
    // User has wired a different asset to this row — leave it alone.
    continue;
}
```

Also clear `m_SubObjectName` and `m_SubObjectType` on the `AssetReference` to avoid stale sub-asset references when re-wiring.

#### 7.5 Inspector button (in the package's main `Editor/`, NOT the sample editor)

Add a path-guarded button to the package's existing custom editor for `AssetConfigsScriptableObject` (or whatever the registry inspector is). The button must invoke the sample's menu via `EditorApplication.ExecuteMenuItem`, NOT a direct method call — the package's main editor assembly cannot reference the sample editor assembly:

```csharp
private bool Is<Sample>SampleConfigs()
{
    var path = AssetDatabase.GetAssetPath(target);
    return !string.IsNullOrEmpty(path) &&
        path.Replace('\\', '/').EndsWith("/<Sample>/<Configs>.asset", StringComparison.Ordinal);
}

private static void OnRefresh<Sample>Sample()
{
    const string menuPath = "Tools/<TeamName>/Samples/<Sample>/Refresh Addressables";
    if (!EditorApplication.ExecuteMenuItem(menuPath))
    {
        Debug.LogWarning($"Menu '{menuPath}' is unavailable. Re-import the sample via Package Manager.");
    }
}
```

Visibility-guard via the path check: the button only appears when the inspected asset is the sample's specific `<Configs>.asset`, not other unrelated `AssetConfigsScriptableObject` instances elsewhere in the user's project.

#### 7.6 Lockstep documentation updates

When adding Track B to a sample, update **all of these in the same change**:

- `Samples~/<Sample>/README.md` — replace any "manual setup" walkthrough with the auto-flow + a "Manual fallback" section + a "Swap in your own content" section (covering the rename pipeline).
- `Samples~/README.md` — sample row "Addressables required?" column flips from "Yes (one-time setup)" to "Yes (auto-setup on import)"; file list adds `Editor/` + `<Content>/` lines.
- `package.json` `samples[]` description — drop any "~N minutes setup" warning; mention the auto-Addressables-on-import behaviour.
- `CHANGELOG.md` — fold into the existing `## [X.Y.Z]` section if pre-publication (per Frameworks `AGENTS.md` *Pre-publication versioning* rule), or create a new section if cutting a release. Mention the sample-scoped editor automation, the dedicated Addressables group name, and the manual escape hatches.
- Package `AGENTS.md` §3 sample row + §4 *Sample Zero-Setup Invariant* (or equivalent) — document the automation surface, the chicken-and-egg safety net, and the user-mapping-respect contract.

Skipping any one of these creates README-vs-source drift exactly like the historical `mobileservices` README issue documented in the Frameworks `AGENTS.md` *Package README accuracy* rule.

## Pitfalls (each has bitten this repo's samples)

### `[CustomEditor(... editorForChildClasses: true)]` + `new InspectorElement(serializedObject)` = editor crash

If the package being sampled has a custom editor on a generic base class with `editorForChildClasses: true`, and that editor calls `new InspectorElement(serializedObject)` from `CreateInspectorGUI()`, **selecting any concrete subclass instance hard-crashes Unity** (`EXC_BAD_ACCESS` SIGILL on the OS Stack Guard region, ~5,000 levels of mutual recursion in JIT-compiled C# code). The bug stays latent until the first concrete subclass exists — exactly when this skill ships its first sample. Fix is in the package, not the sample: replace `InspectorElement` with manual `serializedObject.GetIterator()` + `PropertyField` iteration, then `root.Bind(serializedObject)`. See `Packages/com.gamelovers.services/Editor/Inspectors/AssetConfigsScriptableObjectEditor.cs` for the canonical fixed pattern.

### Hand-authored `.asset.meta` `mainObjectFileID` corruption

For ScriptableObject `.asset` files in `Samples~/`, Unity rewrites `mainObjectFileID` to `0` if the script type wasn't compiled when the asset was first imported (and does NOT auto-fix it on later compiles). The asset still loads, but selection in the Project window can hard-crash Unity via the inspector path above. Set `mainObjectFileID: 11400000` (canonical SO fileID matching the `&11400000` MonoBehaviour anchor in the asset YAML) and right-click → Reimport. Avoid bulk `cp -R` mirrors when reconciling — they silently propagate corruption back into the package source. Prefer named-file `File.Copy` from the editor utility.

### Default interface methods are interface-only at the call site

C# 8 default interface methods (e.g. `IAssetAdderService.AddConfigs<TId, TAsset>`) can only be invoked through the interface, not through the concrete type. The driver's resolver field must be typed as the interface (`private IAssetAdderService _resolver`) — typing it as the concrete (`private AssetResolverService _resolver`) produces `CS1061: 'AssetResolverService' does not contain a definition for 'AddConfigs'`. Same applies for any other default-method API in the package being sampled.

### Sample bullet/asset spawn in world space at the Canvas's `transform.position`

`canvas.transform.position` for a Screen-Space-Overlay Canvas is `(screenWidth/2, screenHeight/2, 0)` in world space (so ~`(640, 360, 0)` for a 1280x720 reference). Spawning prefab pool entries at `transform.position` of the driver puts them off-camera. Use `Vector3.zero` plus an explicit world-space offset based on `Camera.main` instead.

### Bullet pool entries that drift forever

Pool entries that move (e.g. `transform.position += Vector3.up * speed * dt`) need automatic despawn or they accumulate and leak. The driver's `Update` should tick a `pool.SpawnedReadOnly` snapshot and despawn entries whose `Camera.main.WorldToViewportPoint(entry.transform.position)` is outside `[-0.05, 1.05]`. Use a despawn buffer (`List<T>` cleared each tick) — modifying the pool's spawned list during enumeration throws.

### Track B: post-processor misses its own first import

`AssetPostprocessor.OnPostprocessAllAssets` shipped inside `Samples~/<Sample>/Editor/` compiles AFTER the import batch that brings its source file into the consumer's project. So the post-processor MISSES its own first invocation against the same-batch sprites/prefabs/scenes — the user imports the sample, nothing happens, and pressing Play hits the manual-setup error path. Always pair the post-processor with `[InitializeOnLoadMethod]` (deferred via `EditorApplication.delayCall`) as a safety net. The two triggers route through the same idempotent `RunSilent()` so the safety net is harmless on subsequent reloads.

### Track B: don't reference the sample editor assembly from the package main editor

If the package's main `Editor/` assembly adds a sample-specific affordance (e.g. a button on the sample's `<Configs>.asset` inspector), DO NOT add a compile-time `.asmdef` reference to the sample editor assembly. The sample is opt-in; consumers who don't import it will get unresolved-reference compile errors in the package main editor. Use `EditorApplication.ExecuteMenuItem("Tools/.../<verb>")` to invoke the sample's automation across the boundary, and guard the caller-side UI (the button) with an asset-path check so it only appears when the inspected context belongs to the sample. The button stays hidden cleanly if the sample is removed.

### Track B: never overwrite user mappings to other assets

The `RunSetup` pipeline's row-wiring stage MUST respect existing user mappings. When a `Pair.Value.m_AssetGUID` is non-empty AND differs from the canonical asset's GUID, skip the row — the user has wired their own asset to that ID and the automation must not clobber it. Test: if a user replaces `Hero.png` with their own `MyHero.png` and re-maps the row by hand, then drops a fresh `Hero.png` back into the content folder, the row should stay pointing at `MyHero.png`. The automation only fills empty rows or refreshes rows that already point at the canonical asset's current GUID.

### URP vs Built-in render pipeline material color

Tinting a runtime-generated primitive material requires setting BOTH `_BaseColor` (URP/HDRP Lit) and `_Color` (Built-in Standard) so the color is visible regardless of the consumer project's render pipeline:

```csharp
var mat = renderer.material; // forces a unique instance
var color = new Color(1f, 0.55f, 0.1f, 1f);
if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
if (mat.HasProperty("_Color")) mat.SetColor("_Color", color);
```

## Anchor patterns (copy/paste references)

**Track A — Authoring-time UI**:
- `Packages/com.gamelovers.services/Samples~/ServicesPlayground/ServicesPlaygroundUI.cs` — driver with `[SerializeField]`-grouped buttons, `EnsureInputModuleOnEventSystem`, drag-preserving auto-scroll, `WorldToViewportPoint` despawn tick.
- `Packages/com.gamelovers.services/Samples~/AssetResolver/AssetResolverExample.cs` — minimal driver shape with `[SerializeField]` Button refs and friendly error handling for missing service prerequisites.
- `Packages/com.gamelovers.services/Samples~/<sample>/<Sample>.unity` + `<Sample>UI.prefab` — completed prefab + scene shapes the editor utility produces.

**Track B — Consumer-time content automation**:
- `Packages/com.gamelovers.services/Samples~/AssetResolver/Editor/AssetResolverSampleSetup.cs` — full `RunSetup` pipeline (self-locate → bail-out → 3-pass rename → group create → entry mark → SerializedObject row-wire) plus the `AssetResolverSampleAssetPostprocessor` post-processor and the `[InitializeOnLoadMethod]` safety net.
- `Packages/com.gamelovers.services/Samples~/AssetResolver/Editor/GameLovers.Services.Samples.AssetResolver.Editor.asmdef` — canonical sample editor `.asmdef` shape with Addressables references by GUID.
- `Packages/com.gamelovers.services/Editor/Inspectors/AssetConfigsScriptableObjectEditor.cs` — `IsAssetResolverSampleConfigs()` path-guard + `OnRefreshAssetResolverSample()` invoking the sample menu via `ExecuteMenuItem`. Reference for keeping the package main editor decoupled from the sample editor assembly.
- `Packages/com.gamelovers.services/AGENTS.md` §4 *Sample Zero-Setup Invariant* — documented contracts for the AssetResolver sample's automation (sample-scoped lifetime, idempotency, user-mapping respect).

## Coordination with other skills / rules

- The workspace rule "Newly created files / folders... will not have `.meta` files until Unity opens the project" applies to the editor utility itself (created during the workflow); the samples' `.meta` files are produced by Unity when the prefab is saved via `PrefabUtility`, so they're never hand-authored.
- For Track B: the sample editor `.cs` and `.asmdef` `.meta` files MUST be hand-authored with deterministic GUIDs (per the package's *Sample meta-file policy* in its `AGENTS.md` §4). Folder `.meta` files inside `Samples~/` are not required (Unity treats `Samples~` as a non-asset folder); only file-level `.meta` are needed.
- Per the workspace `package-docs-audit` skill: any new sample requires updating `Samples~/README.md` (master index), the per-sample `README.md`, the `samples[]` block in `package.json`, AND the package `AGENTS.md` §3 sample row in lockstep. Don't update only one.
- Frameworks `AGENTS.md` §2 *Sample-scoped editor automation* is the canonical rule for Track B's three contracts (lifetime, chicken-and-egg, decoupling). When this skill ships Track B for a new sample, point reviewers at that rule rather than re-explaining the rationale in the per-sample README.
