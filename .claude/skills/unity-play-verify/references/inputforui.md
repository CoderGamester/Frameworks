# Unity InputForUI Verification

Use this reference for Unity 6 runtime UI Toolkit samples that receive events through InputForUI instead of a uGUI `EventSystem`.

## Preconditions

- Record the full Unity editor version.
- Confirm Active Input Handling satisfies the package contract. If the package depends on Input System, test New or Both and describe Legacy-only as unsupported.
- Confirm the active provider is the expected InputForUI provider, such as `UnityEngine.InputSystem.Plugins.InputForUI.InputSystemProvider`.
- Count uGUI `EventSystem` objects in the active scene and `DontDestroyOnLoad` hierarchy. Require zero when the migration contract removes uGUI.

## Required interaction

Use a real foreground mouse or touch action against the Game or Device Simulator view. Exercise at least:

1. Pointer movement into an enabled control.
2. Pointer down and up inside the control.
3. One observable action committed exactly once.
4. Navigation to a different view or another distinct control path.
5. Content drag inside a ScrollView when the sample is mobile-style.

A programmatic callback, `ClickEvent` dispatch, direct handler call, focused element, or enabled button proves less than real pointer interaction. An injector report with zero pointer moves, downs, or ups is a failed attempt even if the UI rendered.

## Report identity

Write a non-empty report containing:

```text
runId=
codeIdentity=
editor=
initialScene=
finalScene=
interactionDriver=
inputProvider=
eventSystems=
observableAction=
screenshotBytes=
result=
```

Keep failed attempts under their own run identities. Never rename an older failure into the current result or reuse its screenshot.
