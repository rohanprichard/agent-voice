# Native notch call UI

## Current state

The last commit had a glow-only helper. The current uncommitted `native/NotchGlow.swift` also draws a black call surface and native buttons.

The current helper sends button actions to Electron. `desktop/main.cjs` hides the old pill when the native panel owns the call.

This code needs a visual check on the built app. The presence of a native panel in source does not show that it joins the physical notch.

## Screen geometry

Apple supplies the visible top-left and top-right screen areas through `NSScreen.auxiliaryTopLeftArea` and `auxiliaryTopRightArea`. These rectangles use global screen coordinates. The horizontal gap gives the camera housing width. `NSScreen.safeAreaInsets.top` gives its vertical safe-area depth. [Apple left area](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytopleftarea-uglc), [Apple right area](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytoprightarea-gr2n), [Apple safe area](https://developer.apple.com/documentation/appkit/nsscreen/safeareainsets).

Use `screen.frame.maxY` for the panel top. `visibleFrame` excludes the menu bar and the top areas beside the camera housing. Thus, `visibleFrame.maxY` puts a panel below the notch. [Apple visible frame](https://developer.apple.com/documentation/appkit/nsscreen/visibleframe).

The current Mac reports a 220 pt gap and a 38 pt depth. These values come from the [local probe](NOTCH_GLOW_PROBE.md).

The public screen properties do not give the exact corner curve. The current Bezier curve uses a guessed shoulder width.

The current call surface also puts glow around the full black panel. The reference shows a subtle glow near the notch edge. This is a design difference that needs a visual check.

Keep the camera region empty of text and controls. Put compact content on the visible left and right sides. Put larger content below the 38 pt camera region. [Apple left area](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytopleftarea-uglc), [Apple right area](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytoprightarea-gr2n).

## Window and surface

### Native panel or Electron window

Electron can draw a transparent window and show it without focus. It can set a high window level and show the window in full-screen spaces. [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window).

Electron can also send all mouse clicks through a window. This switch applies to the whole window, so it cannot leave active buttons inside that window. [Electron mouse events](https://www.electronjs.org/docs/latest/api/browser-window#winsetignoremouseeventsignore-options).

Electron `screen` gives display bounds and work areas. Its public `Display` values do not include the camera gap or depth. A native helper can measure those values and send them to Electron. [Electron screen](https://www.electronjs.org/docs/latest/api/screen), [Electron Display](https://www.electronjs.org/docs/latest/api/structures/display).

Thus, a native panel is not a technical requirement for the visible shape. It is the shorter path to exact AppKit placement and native button behavior.

Keep Electron for audio, settings, and call state. Use the native panel for the notch surface and call controls. This is a design recommendation, not a limit of Electron.

The original Clicky author published an older Swift app with two `NSPanel` windows. The author says newer code is private. Thus, the public source does not show how the current HeyClicky notch works. [Original Clicky source](https://github.com/farzaa/clicky).

Use one borderless, nonactivating `NSPanel` with a transparent window background. Draw a black shape that starts at the screen top and extends below the camera housing. The physical housing then forms the center of the surface. AppKit says a nonactivating panel does not activate its app. [Apple panel style](https://developer.apple.com/documentation/appkit/nswindow/stylemask-swift.struct/nonactivatingpanel), [NotchApp panel source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchPanel.swift).

Use a black fill near the housing. Put the selected glow on the outside edge of the visible shape. Make the glow part of the same surface, so the line and controls move together. [NotchApp shape source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchPanelShape.swift), [NotchApp shell source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchShellView.swift).

`NotchApp` places its panel at `.popUpMenu`. Its panel joins all Spaces and full-screen spaces. Apple defines these window behaviors. [NotchApp panel source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchPanel.swift), [Apple window behavior](https://developer.apple.com/documentation/appkit/nswindow/collectionbehavior-swift.struct).

Use `NSPanel.becomesKeyOnlyIfNeeded` for controls that do not need keyboard input. A borderless window cannot become key by default. If a later panel contains a text field, a subclass must permit key status. [Apple panel key behavior](https://developer.apple.com/documentation/appkit/nspanel/becomeskeyonlyifneeded), [Apple key window behavior](https://developer.apple.com/documentation/appkit/nswindow/canbecomekey).

The current helper sets `ignoresMouseEvents = true`. The new call panel must receive clicks in its controls. Keep its frame close to the visible call surface. Set a smaller frame for connected calls and a wider frame for ringing. This keeps the transparent area from blocking other apps. `NotchKit` changes its panel frame for open and closed states. [Apple mouse events](https://developer.apple.com/documentation/appkit/nswindow/ignoresmouseevents), [NotchKit window source](https://github.com/aishwaryaashok14/notch-kit/blob/4119779dc4c211c9584af7f97554c4e17bc91891/NotchKit/NotchWindow.swift).

Do not set `ignoresMouseEvents` while a call control is visible. Set it for the idle glow, or hide the panel when idle. The whole window ignores clicks when that property is true. [Apple mouse events](https://developer.apple.com/documentation/appkit/nswindow/ignoresmouseevents).

## Call states

| State | Visible content | Action |
| --- | --- | --- |
| Idle | Physical notch and no surface | Open a small surface on hover. |
| Ringing | A black surface under the notch, the agent name, and two compact controls | Answer or decline. |
| Connected | A smaller black surface under the notch | Open the transcript, mute, or end the call. |
| Listening | Connected controls and a soft white edge | Keep the controls available. |
| Thinking | Connected controls and a soft violet edge | Keep the controls available. |
| Speaking | Connected controls and the selected color | Keep the controls available. |
| Muted | Connected controls and a clear mute sign | Let the user unmute. |
| Ending | The surface contracts into the notch | Remove the panel after the motion ends. |

The ringing and connected states need a visible black surface. A line around the housing alone cannot show the call name or controls. The end-call control must be smaller than the current large button. The source of truth for these states is the existing call state in `desktop/main.cjs`.

## App connection

1. Extend the native helper input with the call ID, agent name, mute state, and call state.
2. Send answer, decline, mute, end, and transcript actions from the helper to Electron.
3. Route those actions through the existing call commands in `desktop/main.cjs`.
4. Stop the Electron call window when the native panel owns the call controls.
5. Keep the transcript in a separate, movable window.
6. Use the old Electron call surface only when a native panel cannot start or the display has no camera housing.

`NotchKit` shows a compact surface with content on both sides of the camera region. It expands the surface below that region when the pointer enters. Its panel uses a clear background and full-screen behavior. [NotchKit window source](https://github.com/aishwaryaashok14/notch-kit/blob/4119779dc4c211c9584af7f97554c4e17bc91891/NotchKit/NotchWindow.swift), [NotchKit panel source](https://github.com/aishwaryaashok14/notch-kit/blob/4119779dc4c211c9584af7f97554c4e17bc91891/NotchKit/NotchPanel.swift).

## Displays and full-screen apps

Use the first screen with a valid camera gap for the native notch panel. If a call starts on an external display, keep the notch panel on the built-in display. Use the Electron fallback on a Mac without a camera housing. `NotchApp` uses this display order. [NotchApp geometry source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchGeometry.swift).

Recompute the screen and panel frame after `NSApplication.didChangeScreenParametersNotification`. This event occurs when the display configuration changes. Do not keep a stale `NSScreen` or frame after a display change. [Apple screen change notification](https://developer.apple.com/documentation/AppKit/NSApplication/didChangeScreenParametersNotification), [NotchApp controller source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchWindowController.swift).

Use `.fullScreenAuxiliary` only after a full-screen check on this Mac. It permits the panel on the same space as a full-screen window. An always-visible call control can cover full-screen content. [Apple window behavior](https://developer.apple.com/documentation/appkit/nswindow/collectionbehavior-swift.struct), [NotchApp panel source](https://github.com/erwinzhang7/NotchApp/blob/f6ab5deed8b18f4d8e600ca27f2b68dbeccaad11/Sources/NotchShell/NotchPanel.swift).

## Visual check

Run the built app with a real or local call state. Capture the full screen for each state. The captures must show one black notch surface, its controls, and no old pill. Check each control with a click. Check the built-in display, an external display, and a full-screen app.

A macOS screen capture cannot show the physical camera housing itself. The capture can show the visible pixels around it. Check the seam on the physical display as well as the capture.
