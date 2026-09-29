# HeyClicky source and reuse

Research date: September 23, 2026. All external sources below were examined on this date.

## Result

Public source exists for the earlier Clicky app. The current HeyClicky app includes later private code.
The author states this distinction in the April 27, 2026 update to the original repository.
The public source uses the MIT license. [Author notice](https://github.com/farzaa/clicky/blob/a80fa80721a8aebe51a170a7780705024ebc6e46/README.md)

The download link on the official site points to a binary release in `farzaa/clicky-releases`.
That repository contains `README.md` and `appcast.xml` at the examined commit.
It supplies the update feed and release binaries, not the application source.
The separate `farzaa/clicky` repository contains the Swift application, Xcode project, tests, and Cloudflare Worker.
[Official site](https://www.heyclicky.com/), [release repository](https://github.com/farzaa/clicky-releases/tree/8572367a3285157ec2e1546fde6bf1b074621cc9), [source repository](https://github.com/farzaa/clicky/tree/a80fa80721a8aebe51a170a7780705024ebc6e46)

I read public files and repository metadata. I did not download or run the app.
I did not install dependencies. Source access does not establish that the code builds or works on the current system.

## Features in the public source

The following files belong to original Clicky commit `a80fa80721a8aebe51a170a7780705024ebc6e46`.

| Feature | Evidence | Reuse fit |
| --- | --- | --- |
| Screenshots | `CompanionScreenCaptureUtility.swift` captures connected displays through ScreenCaptureKit. It excludes its own windows and retains image dimensions and display bounds. | Useful reference for display selection, scaling, and exclusion of overlays. Swift code needs a native helper or a JavaScript rewrite. |
| Cursor overlay | `OverlayWindow.swift` creates transparent windows that ignore mouse input. It tracks the cursor and animates a pointer toward a target. | Reuse the behavior and coordinate rules in a separate Electron window. |
| Target coordinates | `CompanionManager.swift` parses `[POINT:x,y:label:screenN]` tags and removes them from spoken text. | Useful reference for target messages. TalkToMe can use structured tool data instead of text tags. |
| Coordinate conversion | `ElementLocationDetector.swift` scales image coordinates into display points. It returns a target position from a model response. | Useful reference for image scaling. The file does not execute the model's requested click. |

Sources: [screen capture](https://github.com/farzaa/clicky/blob/a80fa80721a8aebe51a170a7780705024ebc6e46/leanring-buddy/CompanionScreenCaptureUtility.swift), [overlay](https://github.com/farzaa/clicky/blob/a80fa80721a8aebe51a170a7780705024ebc6e46/leanring-buddy/OverlayWindow.swift), [target parser](https://github.com/farzaa/clicky/blob/a80fa80721a8aebe51a170a7780705024ebc6e46/leanring-buddy/CompanionManager.swift), [coordinate conversion](https://github.com/farzaa/clicky/blob/a80fa80721a8aebe51a170a7780705024ebc6e46/leanring-buddy/ElementLocationDetector.swift).

The current product has more features than these public files establish.
The official changelog dates computer control to May 4, 2026, with credit to Cua.
It dates initial screen guidance to May 30, user annotations to June 18, and expanded drawing to June 19.
These dates follow the author's April notice about private development.
I found no public source for those exact HeyClicky implementations.
This finding does not prove that no public copy exists elsewhere. [Official changelog](https://www.heyclicky.com/changelog)

## Other public code

| Project | Source and license | Fit for TalkToMe |
| --- | --- | --- |
| `tekram/clicky-windows` | Separate Electron and TypeScript implementation. Its [MIT license](https://github.com/tekram/clicky-windows/blob/c935b10887f2d4018380e199c309f7ec337ff8c7/LICENSE) names tekram. | Closest implementation reference for desktop screenshots and pointer overlays. It targets Windows. macOS behavior needs tests. |
| Electron | [Screen capture](https://www.electronjs.org/docs/latest/api/desktop-capturer) and [window controls](https://www.electronjs.org/docs/latest/api/browser-window). [MIT license](https://github.com/electron/electron/blob/main/LICENSE). | Already part of TalkToMe. It can supply screenshots and transparent overlay windows. |
| Playwright | [Browser actions](https://playwright.dev/docs/input). [Apache-2.0 license](https://github.com/microsoft/playwright/blob/main/LICENSE). | Browser control through a separate browser session. It does not supply desktop annotations. |
| Rough.js | [Lines, curves, circles, and polygons](https://github.com/rough-stuff/rough). [MIT license](https://github.com/rough-stuff/rough/blob/master/LICENSE). | Optional shapes for the Canvas view or a desktop overlay. TalkToMe must supply annotation state and input handling. |
| Cua Driver | Public desktop and browser control with Python and TypeScript interfaces. [Driver source](https://github.com/trycua/cua/tree/main/libs/cua-driver), [MIT license](https://github.com/trycua/cua/blob/main/LICENSE.md). | Candidate for later desktop control. The official HeyClicky credit does not establish which Cua code or version it uses. |

The examined Windows version uses `desktopCapturer` and retains both screenshot dimensions and display bounds.
It creates one transparent window per display and calls `setIgnoreMouseEvents(true)`.
Its renderer shows target markers and labels.
These are source findings, not runtime test results.
[Capture source](https://github.com/tekram/clicky-windows/blob/c935b10887f2d4018380e199c309f7ec337ff8c7/src/main/screenshot.ts), [window source](https://github.com/tekram/clicky-windows/blob/c935b10887f2d4018380e199c309f7ec337ff8c7/src/main/index.ts), [overlay source](https://github.com/tekram/clicky-windows/blob/c935b10887f2d4018380e199c309f7ec337ff8c7/src/renderer/overlay/index.html)

Cua lists separate licenses for optional components and model files.
Its optional `cua-som` package uses AGPL-3.0-or-later.
Its optional perception extension includes model files with separate terms.
The root MIT license does not replace those terms. [Cua license boundaries](https://github.com/trycua/cua#license)

## Reuse terms

The original Clicky MIT license permits use, modification, distribution, and sale.
Copies or substantial portions must retain its copyright notice and permission notice.
For copied code, retain the complete license text with the distribution.
The license names `Copyright (c) 2026 Farza`.
This license covers the public software. It does not establish permission to copy later private code.
[Original license](https://github.com/farzaa/clicky/blob/a80fa80721a8aebe51a170a7780705024ebc6e46/LICENSE)

The same notice condition appears in the other MIT licenses above.
For Playwright redistribution, Apache-2.0 requires the license and applicable notices.
It also requires notices in modified files and applicable attribution from a supplied `NOTICE` file.
[Playwright license, section 4](https://github.com/microsoft/playwright/blob/main/LICENSE)

## Fit for the current app

TalkToMe uses Electron with a Python server. Its renderer uses plain JavaScript.
The desktop code permits microphone access but denies video requests.
The current Model Context Protocol (MCP) tools handle voice messages and call state.
They do not expose screenshots, browser actions, or annotations.
[Package configuration](../../../package.json), [Python configuration](../../../pyproject.toml), [desktop process](../../../desktop/main.cjs), [preload bridge](../../../desktop/preload.cjs), MCP tools (since removed)

Recommendation: keep the Canvas design as the main app surface.
Use Electron for screen capture and desktop overlays.
Use the public Clicky files as implementation references.
This recommendation follows the existing Electron architecture and the source comparison above.

The Canvas view can show a screenshot and its annotations inside the app.
A separate transparent window must show annotations above other applications.
The screenshot message should include a display identifier, image dimensions, display bounds, and capture time.
Those fields let both views use the same target coordinates.
These are proposed TalkToMe design choices, not claims about the private HeyClicky implementation.

Browser control can remain with the connected agent's tools or use Playwright in a separate browser session.
Playwright already appears as a development dependency. That does not make browser control a product feature.
Cua needs a separate integration decision if TalkToMe later controls native applications.
[Current dependencies](../../../package.json), [Playwright actions](https://playwright.dev/docs/input), [Cua interfaces](https://github.com/trycua/cua/blob/main/libs/cua-driver/README.md)

Future tests must cover display scaling, negative display origins, display changes, and the removal of stale annotations.
Screen capture on macOS requires separate user consent.
Electron documents this requirement and the methods that make overlay windows ignore mouse input.
[Capture permission](https://www.electronjs.org/docs/latest/api/desktop-capturer), [mouse input](https://www.electronjs.org/docs/latest/api/browser-window#winsetignoremouseeventsignore-options)
