# UPM Compatibility and Dependency Changes

Use this reference when adding or removing a package dependency, changing supported Unity streams, replacing a sample input/UI backend, or changing asmdef references.

## Establish ownership

For every dependency under review, identify:

- The exact API references and the runtime, Editor, test, or sample assembly containing them.
- Whether Unity supplies the capability as an engine module, a direct package, or a transitive dependency.
- Whether only optional imported sample code needs it.
- Which supported editor and dependency versions expose the replacement API.

Search package code, asmdefs, metadata, samples, tests, and documentation. Inspect installed editor and `Library/PackageCache` sources when available. Do not infer ownership from the development host's resolved package list; unrelated packages can keep a removed dependency installed.

## Decide against the supported matrix

Use the package's declared supported streams, not every historical Unity version. A replacement is valid only when each supported stream supplies the required API and behavior. Record the exact validation editor for each supported stream and state unsupported input modes or editor streams explicitly.

For UI input, distinguish:

- UI Toolkit runtime input through Unity InputForUI.
- uGUI input through `EventSystem` and an input module.
- Input System APIs still needed by gestures, touch simulation, or gameplay even when uGUI is removed.

Removing uGUI does not imply removing Input System.

## Verify in clean hosts

Create a fresh host for every validation editor and install only the local package plus requirements declared by that package. Import every affected `Samples~` entry through Package Manager or an equivalent consumer copy under `Assets/`.

Require all of the following:

1. The host manifest names the local package and no undeclared development-only package.
2. The resolved lock proves the removed dependency is absent or identifies the separate dependency chain that still owns it.
3. Imported sample runtime and Editor asmdefs compile.
4. Every supported sample scene opens and plays.
5. `unity-play-verify` proves the replacement behavior with real input where applicable.
6. Package tests remain green in every environment required by repository policy.

## Artifact contract

Never overwrite a previous run in place. Give each run an immutable directory or identifier and record:

- Run identifier and start time.
- Source code identity.
- Editor path and full version.
- Direct manifest and resolved lock paths.
- Imported sample path and scene.
- Compile log, behavior report, and screenshot identities.
- Non-empty byte counts for every required output.

A PASS line without these identities is not completion evidence.
