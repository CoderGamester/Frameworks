# UPM Compatibility and Dependency Changes

Use this reference when adding or removing a package dependency, changing supported Unity streams, replacing a sample input/UI backend, or changing asmdef references.

## Establish ownership

For every dependency under review, identify:

- The exact API references and the runtime, Editor, test, or sample assembly containing them.
- Whether Unity supplies the capability as an engine module, a direct package, or a transitive dependency.
- Whether only optional imported sample code needs it.
- Which supported editor and dependency versions expose the replacement API.

Search package code, asmdefs, metadata, samples, tests, and documentation. Inspect installed editor and `Library/PackageCache` sources when available. Do not infer ownership from the development host's resolved package list; unrelated packages can keep a removed dependency installed.

## Define the matrix vocabulary

Keep four facts separate:

- **Minimum Unity version**: the `package.json` `unity` floor.
- **Reference stream**: a selected editor family such as `6000.3.x`.
- **Validated editor**: the exact patch that produced current, attributable evidence.
- **Primary development editor**: the maintainer's normal editor, not the minimum.

Each cell has one of three outcomes: `PASSED`, `FAILED`, or `NOT VALIDATED`. Licensing, network, missing-editor, and harness failures are `NOT VALIDATED`. Never infer every patch in a stream from a different stream or call untested intermediate/future streams supported.

## Decide against the supported matrix

Use the package's declared supported streams, not every historical Unity version. A replacement is valid only when each supported stream supplies the required API and behavior. Record the exact validation editor for each supported stream and state unsupported input modes or editor streams explicitly.

For UI input, distinguish:

- UI Toolkit runtime input through Unity InputForUI.
- uGUI input through `EventSystem` and an input module.
- Input System APIs still needed by gestures, touch simulation, or gameplay even when uGUI is removed.

Removing uGUI does not imply removing Input System.

## Verify installation truth before Unity

Resolve the canonical repository and tag from `.gitmodules`, the package remote, and the README. Then construct the exact consumer manifest.

Git UPM dependencies are not a substitute for a package registry: if package A's `package.json` names package B by semantic version, installing A from Git does not prove Unity can resolve B. Either B must exist in an explicitly configured registry or the README host manifest must install B directly from Git. The development host's embedded packages and direct dependencies can mask this failure.

Record both the declared dependency floor and the effective version selected in the clean lock.

## Verify in clean hosts

Create two fresh hosts for every validation editor:

1. **Current-source host** — installs the package under review from its current workspace path or immutable current commit. This proves the tree being edited.
2. **Pinned-install host** — installs the exact Git URLs and tags printed in the README. This proves the user-facing installation path, not unpublished local work.

Never label a remote-tag run with a workspace code identity. Record the installed path/ref explicitly. Import exactly every declared `package.json` `samples[]` entry through Package Manager or an equivalent consumer copy under `Assets/`; copying the entire `Samples~` directory can accidentally validate undeclared or incomplete material.

Require all of the following:

1. The host manifest names the local package and no undeclared development-only package.
2. The resolved lock proves the removed dependency is absent or identifies the separate dependency chain that still owns it.
3. Imported sample runtime and Editor asmdefs compile.
4. Every supported sample scene opens and plays.
5. `unity-play-verify` proves the replacement behavior with real input where applicable.
6. Package tests remain green in every environment required by repository policy.

Package-specific gates remain open until observed: UI/rendering needs an Editor PlayMode run and inspected image; Mobile Services needs Android and iOS script/build compilation; importer samples need a real fixture and output comparison. A generic batch runner cannot turn these into a full compatibility pass.

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
