# Empty-state layout and persistent chrome

Research date: September 23, 2026.

## Recommendation

Use one alignment column for both states.
Keep the agent-connection control and the settings control in a single header row at the top of the window.
Align the header row's leading and trailing items to the same column as the transcript and the composer.
Move the settings control out of the bottom-left corner, because macOS guidance says to avoid controls at the bottom of a window.
Center the empty state in the gap between the header row and the composer, and let the composer supply the visible column edges.
The rules below follow the cited guidance and the repository measurements recorded at the end.

## The application currently uses two alignment systems

The chrome sits on an 850-pixel column. The empty-state content is capped at 520 pixels and centered in the window.
The settings gear is at the bottom-left of the chrome column and the agent link is at its top-left.
[styles.css](../../../src/talktome/static/styles.css)

At a 1220-pixel window width, the chrome column starts 227 pixels from the window edge and the empty-state block starts 350 pixels from the window edge.
The two lines differ by 123 pixels, so the gear is neither flush with a window structure nor flush with the content.
Apple's layout guidance states the cost of that: "People assume that aligned items are related to each other."
[Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

The live state already replaces the centered block with a compact header and a scrolling transcript, but it keeps the same two width systems.
So the disagreement persists across both states.

## One column with nested measures

Prefer one structural column. Let text measures nest inside it.

- Apple: "Align elements to make them easier to scan, and use indentation to convey hierarchy." Aligned items are read as related.
  [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Nielsen Norman Group: "Grouping is usually conveyed implicitly through proximity and the use of white space or explicitly through enclosure (common region)."
  [Visual Hierarchy](https://www.nngroup.com/articles/visual-hierarchy-ux-definition/)
- Nielsen Norman Group: "Items close together are likely to be perceived as part of the same group — sharing similar functionality or traits."
  [Proximity Principle](https://www.nngroup.com/articles/gestalt-proximity/)

Rules that follow from those sources:

1. Define one shell column. Use a max-width of about 680 pixels, centered, with the window background extending beyond it.
   The range from 640 to 720 pixels works; the constraints are that the empty-state block stays above two thirds of the shell and that the transcript text keeps its own narrower measure.
   The shell carries the header row's items, the transcript, the composer, and the empty-state block.
2. Keep one structural alignment line. Text measures are typographic caps inside the shell, not separate columns.
   The transcript measure stays at or below 80 characters.
   [Visual Presentation](https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html)
3. Let the centered block sit on the shell's axis, and let the chrome sit on the shell's edges.
   A centered block's own edges are necessarily inset from the shell edges, and that is not a second alignment system as long as the block is centered on the same axis and the shell edges are visible.
   Make those edges visible with the composer, which spans the shell in both states.
4. Any element that is not on the shell line must be flush with a visible window edge.
   Do not leave a control in the space between the shell edge and the window edge.
5. Give the header row a boundary in both states, such as a 1-pixel hairline below it.
   A boundary groups its contents and can outweigh proximity alone.
   [Common Region](https://www.nngroup.com/articles/common-region/)
6. Keep that boundary minimal. Nielsen Norman Group warns that repeated containers "create clutter," and Apple reaches the same point with negative space and separator lines rather than cards.
   [Common Region](https://www.nngroup.com/articles/common-region/), [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

## Persistent chrome belongs at the top

macOS gives a specific instruction about bottom-of-window controls: "Avoid placing controls or critical information at the bottom of a window. People often move windows so that the bottom edge is below the bottom of the screen."
[Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

The current gear is at the bottom-left, which is the position that sentence rules out.

Toolbar regions have established meanings.
The leading edge holds navigation and the view title.
The centre holds common controls.
The trailing edge holds "important items that need to remain available," the overflow menu, and the primary action.
"Items on the trailing edge remain visible at all window sizes."
Only one primary action is allowed, and it belongs on the trailing side.
[Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)

Settings has a platform-standard home that is not a toolbar: "Include a settings item in the [App menu]. Avoid adding settings buttons to a window's toolbar, because doing so decreases the space available for essential commands that people use frequently."
[Settings](https://developer.apple.com/design/human-interface-guidelines/settings)

The App menu lists `Settings…` after `About`, and the item is for app-level settings only.
[The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)

macOS-specific guidance makes the same point from the other direction: "Use the menu bar to give people easy access to all the commands they need to do things in your app," while window toolbars are for frequent commands.
[Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos)

People also expect the standard Command-Comma shortcut, and they must suspend their task to open a settings area at all.
[Settings](https://developer.apple.com/design/human-interface-guidelines/settings)

Task-specific options should stay in the view they affect rather than move into settings.
[Settings](https://developer.apple.com/design/human-interface-guidelines/settings)

Rules:

1. Keep both persistent controls in the header row in both states. Nothing moves between the empty state and the live state.
2. Let the header row span the full window width and inset only its items, which is what Material requires of an app bar and what makes the row read as window chrome.
   [App bars](https://m3.material.io/components/app-bars/guidelines)
3. Put the agent-connection control on the leading side, because it reports session identity and status.
   Put settings on the trailing side, which stays visible at all window sizes.
4. Keep the header to at most three groups, and keep only one prominent action in it.
   [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
5. Give settings a second entry point in the App menu with the Command-Comma accelerator.
   The current Electron menu template has `about` and `quit` only, so the visible gear is the sole path today.
   [main.cjs](../../../desktop/main.cjs)
6. Label a control that opens a window with a trailing ellipsis, so `Settings…` in the menu follows the system convention.
   [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
7. Keep the header row clear of the window controls. They are drawn at a 22-point inset in this app, and macOS guidance says to move toolbar items inward rather than let the window controls cover them.
   [Windows](https://developer.apple.com/design/human-interface-guidelines/windows), [main.cjs](../../../desktop/main.cjs)
8. Do not rely on corner and edge targets as an argument for this app. Fitts's law describes screen edges as effectively infinite targets, and a windowed app's inner edges do not have that property.
   [Fitts's Law](https://www.nngroup.com/articles/fitts-law/)

Chrome width and content width do not have to be equal, but they must be related.
A header bar is window chrome, so it spans the window; its items sit on the content column's edges.
The failure mode is a chrome width that is neither the window edge nor the content edge, which is the current 850-pixel column relative to the 520-pixel block.

Two top-of-window options exist, and only one of them fits the existing 48-pixel drag band.
Keeping the drag band and placing the header row below it gives the header a 92-pixel offset from the window top but clears the window controls without special handling.
Reducing the drag band and placing the header inline with the window controls requires a leading inset of roughly 96 pixels, which is what macOS guidance asks for when window controls and toolbar items share a row.
[Windows](https://developer.apple.com/design/human-interface-guidelines/windows)

## Vertical whitespace in an empty state

An empty state has work to do: "Empty states provide opportunities for designers to communicate system status, increase learnability of the system, and deliver direct pathways for key tasks."
The alternative is worse: "Totally empty states cause confusion about how and whether the system is working."
[Empty States in Complex Applications](https://www.nngroup.com/articles/empty-state-interface-design/)

Whitespace communicates grouping when the gaps differ by role: "Grouping related fields together helps users make sense of the information that they must fill in," and increasing the space between groups "makes this 15-field form less overwhelming."
[Group Form Elements Effectively Using White Space](https://www.nngroup.com/articles/form-design-white-space/)

Apple adds a large-screen rule that supports centering rather than edge-to-edge stretching: with resizable windows, "prefer to keep content horizontally centered at very large sizes so people can easily view and interact with it."
That sentence is visionOS guidance, but the size argument transfers to a 1220-pixel desktop window.
[Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

Rules:

1. Split the window into three vertical zones: the fixed top band and header row, a flexible middle zone, and a fixed composer zone.
   Only the middle zone absorbs surplus height.
2. Center the empty-state block in the middle zone, not in the window.
   The middle zone's top edge is the header line and its bottom edge is the composer, so this is the space people read as the empty region.
3. Bias the block upward by roughly 8 to 16 pixels from the geometric centre of the middle zone.
   This is a judgment about optical balance, not a sourced rule.
4. Take every internal gap from one scale.
   Material builds spacing on an 8-pixel scale with sanctioned 4-pixel and smaller units, so use 4, 8, and 16 within a group and 24 or 32 between groups.
   [Spacing](https://m3.material.io/styles/spacing/overview), [Spacing tokens](https://m3.material.io/styles/spacing/tokens)
   Use one value per relationship, so the orb-to-title gap is always the same number.
   Material states the reason directly: "Consistent spacing between related elements or groups makes them easier to navigate with the eye," and "Similar elements should have the same spacing and sizing in a layout to show they're related."
   [Spacing in layouts](https://m3.material.io/foundations/layout/grids-spacing/spacing)
5. Allow exactly one gap to be arbitrarily large: the surplus margin.
   Do not spread the surplus across several medium gaps, because three or more unexplained gaps read as an accident rather than a decision.
6. Treat a surplus larger than roughly twice the block height as a signal to add a bounded element, such as a visible composer boundary or a recent-conversation stub, rather than more space.
   This threshold is a judgment, not a sourced rule.

## Width, measure, and target size

Material provides a target rather than a cap: "Across all breakpoints, adjust margins and type styles to keep text between 40–60 characters per line."
[Breakpoints](https://m3.material.io/foundations/layout/breakpoints/overview)

WCAG provides the outer limit for blocks of text: "Width is no more than 80 characters or glyphs (40 if CJK)."
That is a Level AAA requirement, and it is a cap rather than a target.
[Visual Presentation](https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html)

Nielsen Norman Group supports shorter lines qualitatively: "Shorter lines of text and just right leading … make reading easier."
No numeric characters-per-line figure could be verified from Nielsen Norman Group.
[Good Visual Design, Explained](https://www.nngroup.com/articles/good-visual-design/)

Aim for the Material range on short interface copy and allow up to the WCAG cap for transcript prose.
The measures have to be stated separately from the column, because they disagree in practice.
At the current 13 and 14 pixel type sizes, one character occupies roughly half an em, so 80 characters needs about 560 pixels and 60 characters needs about 420 pixels.
The proposed shell is 680 pixels, so transcript text that spans the shell would run to about 97 characters per line at 14 pixels.
The fix is a measure cap inside the shell, not a narrower shell.

Pointer targets have a Level AA floor: "The size of the target for pointer inputs is at least 24 by 24 CSS pixels," with a spacing exception for undersized targets.
The same page adds that meeting the size requirement regardless of spacing is a best practice.
[Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)

Apple gives a platform value for the same idea. The macOS default control size is 28 by 28 points and the minimum control size is 20 by 20 points.
[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)

Apple also sets spacing between controls: about 12 points of padding around controls that include a bezel, and about 24 points around the visible edges of controls without one.
A button generally needs a hit region of at least 44 by 44 points.
[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)

Fitts's law adds the movement argument: "The larger the target, the shorter the movement time to it," and targets that sit too close together invite overshoot onto the wrong target.
[Fitts's Law](https://www.nngroup.com/articles/fitts-law/)

Contrast has three relevant floors. Text needs 4.5:1, large text needs 3:1, and large means 18 point or 14 point bold, which is approximately 24 and 18.5 pixels.
[Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
Component boundaries, icons, and state indicators need 3:1 against adjacent colours, although the criterion "does not require that controls have a visual boundary indicating the hit area."
[Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

| Element | Rule |
| --- | --- |
| Shell column | Max-width about 680 pixels, centered, about 70 pixels inside each window edge at minimum width |
| Empty-state hero block | Max-width 520 pixels, centered on the shell axis, at least two thirds of the shell width |
| Transcript text | Measure of about 70 characters, never above the 80-character cap |
| Transcript messages | Cap the message width near 500 pixels, not at 90 percent of the shell |
| Title text | Measure of 24 to 34 characters |
| Supporting text | Measure of 40 to 60 characters |
| Primary button | At least 44 points tall, width fitted to its label, centered |
| Composer | Full shell width, input hit area at least 44 points tall |
| Header controls | Visual size at least 28 by 28 points, hit target at least 24 by 24 pixels |
| Spacing between chrome targets | At least 8 pixels, about 12 points around bezelled controls |
| Chrome label text | 4.5:1, or 3:1 at 18 point, or 14 point bold |
| Composer and control boundaries | 3:1 against adjacent colours, or identified by another 3:1 cue |

## Intentional empty state versus sparse empty state

An intentional empty state names the state, explains the feature in one line, and offers exactly one primary action.
It also states whether the system is working, because a total absence of content is read as a fault.
[Empty States in Complex Applications](https://www.nngroup.com/articles/empty-state-interface-design/)

An intentional empty state is bounded. The block is enclosed by visible structure on at least two sides, such as the header hairline above it and the composer boundary below it, and the leftover space appears as one margin outside the block.
Bounding also groups: "items within a boundary are perceived as a group."
[Common Region](https://www.nngroup.com/articles/common-region/)

An intentional empty state keeps every visible control either on the shell line or flush with a window edge, because alignment itself asserts relatedness.
[Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

A sparse empty state shows the opposite pattern: elements pushed to window corners with no shared line, more than one equally weighted action, whitespace split into several unexplained gaps, and at least one control whose only relationship to the content is that it shares the window.
The gear and the agent link currently sit in that last category relative to the 520-pixel block.

The distinction in one sentence: an intentional empty state has a bounded block with one action and one surplus margin, while a sparse one has loose elements and several ambiguous margins.

## Material Design 3

Material Design 3 is a touch-first system, so its density-independent sizes do not transfer directly to a pointer-driven macOS window.
Its layout, spacing, and app-bar model does transfer.

Material defines width breakpoints rather than device types. A breakpoint is "the window size at which a layout needs to change to match available space, device conventions, and ergonomics."
A 1220-pixel window falls in the large class, above the expanded class, because expanded ends at 1199 density-independent pixels.
[Breakpoints](https://m3.material.io/foundations/layout/breakpoints/overview)

Expanded layouts use "a leading and trailing margin of 24dp," and the spacer between panes is also 24dp.
[Expanded](https://m3.material.io/foundations/layout/breakpoints/expanded)

Spacing follows a defined scale: "The spacing system is measured on an 8dp scale, where space100 = 8dp."
Values other than multiples of 8 are used, "like 2dp, 4dp, 6dp, and 10dp."
[Spacing](https://m3.material.io/styles/spacing/overview), [Spacing tokens](https://m3.material.io/styles/spacing/tokens)

At medium widths and above Material replaces the bottom navigation bar with a navigation rail, which holds three to seven destinations, and on large screens "the rail region on the trailing side of a large screen can hold supporting controls or actions."
[Navigation rail](https://m3.material.io/components/navigation-rail/guidelines)

That rail does not fit this application.
TalkToMe has one primary view, not three to seven destinations, and a rail would add a persistent empty strip to an interface whose problem is already unexplained space.
The app bar is the correct container instead.
An app bar "should always span 100% of the window width," should have "one action, two if necessary," places up to two icon buttons "aligned to the trailing edge," and may use either a leading or a centered headline.
[App bars](https://m3.material.io/components/app-bars/guidelines)

Material does not currently publish empty-state guidance. The M3 content-design section has no empty-states page.
The archived M2 page is the surviving official source: "The most basic empty state consists of a non-interactive image and a text tagline," and the tagline should carry a helpful message and "convey the purpose of the screen, without appearing actionable."
[Empty states, M2 archive](https://m2.material.io/design/communication/empty-states.html)

That instruction is about the tagline, not the screen.
It is compatible with the Nielsen Norman Group requirement for a direct pathway, provided the tagline stays plain text and a separately styled control carries the action.
The same archive holds the responsive column system that current M3 pages no longer enumerate: "Material Design provides responsive layouts based on 4-column, 8-column, and 12-column grids," and the grid is "made up of three elements: columns, gutters, and margins."
[Responsive layout grid, M2 archive](https://m2.material.io/design/layout/responsive-layout-grid.html)

## Decision for TalkToMe at 1220x820

The repository facts used here are the 1220 by 820 default window, the 820 by 620 minimum, the hidden-inset title bar with window controls at a 22-point inset, the 48-pixel drag band, the 850-pixel chrome column, the 520-pixel empty-state cap, the 32-pixel gear at the bottom-left, and the 42-pixel top row with the agent link at its leading edge.
[main.cjs](../../../desktop/main.cjs), [styles.css](../../../src/talktome/static/styles.css)

| Question | Decision |
| --- | --- |
| How many alignment columns | One. A shell of about 680 pixels, centered, used in both states |
| Where persistent chrome lives | A 44-pixel header row below the 48-pixel drag band, spanning the window, with items inset to the shell edges |
| Agent connection, empty state | Leading edge of the header row, status dot plus label |
| Agent connection, live state | The same position, unchanged, so it never jumps |
| Settings, empty state | Trailing edge of the header row, 32 by 32 pixels, tooltip "Settings" |
| Settings, live state | The same position, unchanged, plus a primary action on the trailing side if one is needed |
| Settings entry points | Header gear plus App menu `Settings…` with Command-Comma |
| Gear position | Top-right of the header row. Not the bottom-left |
| Empty-state block | Centered in the middle zone, max-width 520 pixels, biased 8 to 16 pixels above the geometric centre |
| Live-state content | Transcript and composer share the shell. The header row is unchanged |
| Do both states share one column | Yes. The state change alters contents, never geometry |

The geometry works at both extremes.
At 1220 pixels, a 680-pixel shell leaves 270 pixels on each side, and a 520-pixel hero leaves 80 pixels inside the shell on each side, so the hero fills 76 percent of the column.
At the 820-pixel minimum width, the same shell leaves 70 pixels on each side and the 520-pixel hero leaves 80 pixels, so no additional breakpoint is needed.
The header row sits below the drag band, so its leading control clears the window controls at every width.

Keeping the 850-pixel column and only moving the gear would not fix the problem.
The 123-pixel offset between chrome and content is the reason the gear looks orphaned, and aligning to either the window edge or the content line removes the ambiguity, while a third width between them preserves it.
In the empty state the mismatch has a second cause: nothing draws the column, so the two controls float without a visible region to belong to.

If the 520-pixel block is kept inside the 850-pixel column, the hero fills 61 percent of the column, which is the ratio that reads as swimming in space.
Either narrow the shell to about 680 pixels or widen the hero to about 560 pixels, but do both from one line.
The live state already shows the second problem directly: the current message width is 90 percent of the content box, which is about 98 characters per line at 14 pixels. [styles.css](../../../src/talktome/static/styles.css)

## Repository measurements

These ratios were computed from the token values in `styles.css` using the WCAG 2.2 relative-luminance formula.
They are measurements of this repository, not quoted guidance.

| Foreground | Background | Ratio | Requirement | Result |
| --- | --- | --- | --- | --- |
| `--muted` #7b817b | `--bg` #f8f9f6 | 3.77:1 | 4.5:1 for normal text | Fails at the 11 to 12-pixel sizes in use |
| `--placeholder` #939b90 | #ffffff | 2.86:1 | 4.5:1 for normal text | Fails |
| `--line` #e3e6df | `--bg` #f8f9f6 | 1.19:1 | 3:1 where it identifies a component | Fails if the border is the only thing identifying the composer |
| `--text` #343a36 | `--bg` #f8f9f6 | 11.01:1 | 4.5:1 | Passes |
| `--accent` #45694f | `--bg` #f8f9f6 | 5.87:1 | 4.5:1 | Passes |

The muted token carries the agent label, the call timer, the privacy note, and the window-bar label.
Those strings are below the normal-text floor, and they are the chrome that this document proposes to keep.
[styles.css](../../../src/talktome/static/styles.css), [Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

The composer's 1-pixel border is nearly invisible against the page.
That matters for this decision because the composer is what makes the column visible in the empty state.
[Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

## Uncertainty

- Apple has no empty-state page. The layout and toolbar guidance used here is platform general and was not written for a 1220 by 820 window.
- The Nielsen Norman Group whitespace article named in the brief does not exist. `https://www.nngroup.com/articles/whitespace/` returns a 404, and no numeric characters-per-line figure could be verified from Nielsen Norman Group at all. The 40-to-60 and 80-character figures in this document come from Material and from WCAG 1.4.8.
- The live Nielsen Norman Group proximity article is `gestalt-proximity`, not `law-of-proximity`; the latter returns a 404.
- Apple's 44-point hit region and its 12-to-24-point padding guidance is written for touch and for bezelled and bezel-less controls generally. The macOS control sizes, 28 by 28 default and 20 by 20 minimum, are the platform-specific values.
- The 8-to-16-pixel upward optical bias and the surplus threshold of twice the block height are this document's judgment.
- WCAG 1.4.11 explicitly does not require a visible boundary on a control, so the composer-border finding is partly a usability argument.
- The claim that the App menu lacks a Settings item was read from the current `desktop/main.cjs` template. It can change, and macOS also exposes settings through the app menu role behaviour.
- Material Design 3 pages are client-rendered, so their article text was retrieved through the `r.jina.ai` rendering proxy after confirming each canonical URL returns HTTP 200. The quotes were read from the rendered canonical pages, and the layout conclusions are only as reliable as that rendering.
- Several Material paths are stale. `foundations/layout/understanding-layout/overview` and `foundations/layout/applying-layout/window-size-classes` return 404, "window size class" is now "breakpoint," and "top app bar" is now "app bar." Material 3 has no empty-state page, so the empty-state model used here comes from the unmaintained M2 archive.
- Material does not state where a settings destination belongs. Its app-bar guidance permits global product controls in the app bar, and that sentence is the basis for placing settings there.
- Material's 8-pixel spacing scale and its sanctioned 2, 4, 6, and 10-pixel values were used for the gap scale. The "4dp baseline grid" language appears only in the archived M2 spacing page, not in current M3.
- Material's target sizes, notably 48 density-independent pixels, were treated as not applicable to a pointer-driven macOS window. Only its layout, spacing, and app-bar rules were used.

## Measurements before adoption

1. Record the leading-edge offset of the header's first control and the composer's leading edge at 1220, 1000, and 820 pixel widths.
2. Record the vertical centre of the empty-state block against the middle zone at 820 by 620.
3. Verify that the header's leading control never overlaps the window controls at any width.
4. Measure the contrast of every chrome label, icon, and boundary after the change, in both themes.
5. Confirm that no control changes position between the empty and live states.
6. Confirm that the composer boundary reaches 3:1, or that the field is identified by another 3:1 cue.
7. Re-measure the gear and agent-control hit targets against the 24-pixel floor and the 28-point platform default.
8. Re-check the empty state with a long agent name, a long title, and the largest supported text size.
