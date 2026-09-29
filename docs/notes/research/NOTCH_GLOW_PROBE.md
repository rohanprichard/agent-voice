# Native notch glow probe

Date: September 25, 2026.

The source is [NotchGlow.swift](../../../native/NotchGlow.swift).
It uses `NSScreen.auxiliaryTopLeftArea`, `auxiliaryTopRightArea`, and
`safeAreaInsets.top` to find the notch gap. It creates a transparent `NSPanel`
at the status bar level. The panel passes mouse input through to the desktop.

The probe reported this geometry on the test Mac:

| Measurement | Value |
| --- | ---: |
| Screen | 1800 × 1169 pt |
| Left notch edge | 790 pt |
| Right notch edge | 1010 pt |
| Notch width | 220 pt |
| Notch depth | 38 pt |

I built the probe in `/tmp/talktome-notch-probe`. I opened its temporary app
and examined the panel screenshot. The first curve looked too square and bright.
I changed the shoulders and made the line softer. The new curve narrows from
220 pt at the top to about 122 pt at the bottom.

The app build includes the Swift helper. Electron sends the call state and the
selected color to the helper through standard input. The helper uses the call
state to set the glow color and strength. It shows no glow when the app is idle.
The helper draws a soft glow when the pointer is near the notch. It moves the
panel after a display change.

I built `dist/app/mac-arm64/TalkToMe.app` and opened it. The app started the
native helper and the local server. The bundle also contains the helper at
`Contents/Resources/notch-glow/notch-glow`. Its `--geometry` command returned
the same 220 pt width and 38 pt depth from the bundle.

The public API gives a gap and a depth. It does not give the exact corner
curve. The helper draws that curve. The panel screenshot shows the shape, but
a macOS screen capture cannot show the physical notch. A later visual check
on the physical display can refine the curve for each Mac model.

Sources: [Apple screen safe areas](https://developer.apple.com/documentation/appkit/nsscreen/safeareainsets),
[Apple top-left auxiliary area](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytopleftarea-uglc),
and [NotchApp's public AppKit approach](https://github.com/erwinzhang7/NotchApp).
