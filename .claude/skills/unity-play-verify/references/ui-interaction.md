# Unity UI Interaction Verification

Use this reference for uGUI or UI Toolkit buttons, navigation, ScrollViews, pointer capture, press feedback, safe areas, or Device Simulator input.

## Evidence levels

Do not conflate these observations:

1. **Handler invocation:** a method or callback produces its expected effect when called directly.
2. **Control dispatch:** the UI framework raises a click/submit event for the control.
3. **User interaction:** a real mouse/touch press reaches the control, survives eligibility checks, and produces the effect.
4. **UX result:** the visual, haptic, navigation, or system outcome is understandable and consistent.

A Console log establishes at most handler entry. It does not prove dispatch, interactability, native behavior, or UX.

## Before changing input code

Observe one failing interaction and identify:

- The element under the pointer.
- Which element captures the pointer.
- Whether movement events arrive.
- Whether the interaction ends through pointer up, pointer cancel, capture out, disable, or scene change.
- Whether a ScrollView manipulator, Button manipulator, custom gesture controller, overlay, or navigation layer consumes propagation.

Use temporary, narrowly scoped diagnostics only when necessary. Remove them before completion.

Do not add a custom gesture fallback until the observed event path proves the framework is missing a required event. A second recognizer can steal capture, cancel clicks, leave pressed classes active, or make bottom navigation intermittently unreachable.

## Button lifecycle matrix

Exercise every distinct button implementation, plus every control with special wiring:

| Interaction | Required observation |
|---|---|
| Pointer down, hold | Pressed visual appears once |
| Pointer up inside | Pressed visual clears and action occurs once |
| Pointer up outside | Pressed visual clears and action does not occur |
| Drag past threshold | Pressed visual clears, click is cancelled, scrolling may take over |
| Pointer cancel | Pressed visual clears |
| Pointer capture loss | Pressed visual clears |
| Control disabled | Disabled style appears and stale pressed state clears |
| Scene/navigation change | No stuck visual, duplicate action, or orphaned capture remains |

Verify the expected effect, not merely a log. For native-only behavior that cannot occur in the Editor, verify the simulator contract or an explicit on-screen unsupported/no-op status, then validate on a device when required.

## Scroll matrix

For every scrollable page, test:

- Mouse wheel/trackpad over content.
- Dragging the scrollbar.
- Press-drag-release starting on non-control content.
- Press-drag-release starting on a button and exceeding the drag threshold.
- A short stationary button press.
- Momentum/inertia after release where enabled.
- Reaching the first and last content rows.
- Bottom navigation remaining fixed and clickable while content is scrolled.

Scrolling only through the scrollbar is a failure for a mobile-style interface. Intermittent content drag usually indicates competing pointer capture, propagation cancellation, an overlay intercepting input, or a custom recognizer disagreeing with the ScrollView.

## Responsive and safe-area checks

Capture representative notched iOS and Android profiles. Check:

- One layer owns each safe-area inset; padding is not applied twice.
- Navigation is inside the safe area but outside page scrolling.
- Action rows wrap only when their readable minimum widths no longer fit.
- Wrapped labels may use two lines without clipping or inconsistent button height.
- Buttons in the same semantic group share visual styling.
- Content remains reachable in portrait and landscape when both are supported.

## Completion report

State:

- Which Editor and scene were used.
- Whether Unity MCP, computer-use, or direct invocation drove each check.
- Which device profiles/orientations were inspected.
- Which controls and scrolling paths were exercised.
- Any behavior that still requires a physical Android/iOS device.

Never describe direct callback invocation as a successful click test.
