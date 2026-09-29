# Background texture for a mostly empty desktop surface

Research date: September 23, 2026.

## Recommendation

Put the grain in the background paint of the shell, not on top of the interface.
Blend it with the background color by plain alpha compositing, and set the strength with the noise tile's own alpha.
Do not use `mix-blend-mode: overlay` at a few percent opacity over a near-white or near-black surface.
On both flat themes that combination measures as no visible change at all. Values below are measured, not estimated.

The recommended tile is 160 by 160 user units, `type="fractalNoise"`, `baseFrequency="0.8"`, `numOctaves="2"`, `stitchTiles="stitch"`, a fixed `seed`, `color-interpolation-filters="sRGB"`, desaturated, with alpha scaled by `feFuncA`.
The light theme uses an alpha slope near `0.035`; the dark theme uses one near `0.010`.
Each value is a starting point for visual tuning, not a finished design decision.

## What Arc does

Arc's own marketing site paints noise as a background image over a flat brand color, with no blend mode.
For example `background: var(--colors-brandBlue); background-image: url(/noise-light.png)`.
[arc.net stylesheet](https://arc.net/).

`noise-light.png` is 220 by 220 pixels, an 8-bit palette PNG with a transparency chunk, and no alpha above 41 of 255.
Its mean alpha is 16.5 of 255, or about 6.5 percent.
The file is opaque in format terms and translucent in content terms, so its own alpha channel is what sets the grain strength.
No `background-size` or `background-repeat` is declared, so the tile repeats at its natural 220 pixel size.
These are measurements of the served asset, taken from [noise-light.png](https://arc.net/noise-light.png).

The site does use blend modes elsewhere, but not for grain.
One quote block sets `mix-blend-mode: overlay` on text, and a masked variant puts the noise under a `mask-image`.
[arc.net stylesheet](https://arc.net/).

The Arc application exposes grain as a user setting.
The May 26, 2022 release notes describe "Advanced Theme options for Spaces" where a user can "increase Intensity or Graininess in the Space Theme editor".
[Arc for macOS 2022 release notes](https://resources.arc.net/hc/en-us/articles/20498417809815-Arc-for-macOS-2022-Release-Notes).

Space Themes are gradient based, and a Theme Picker applies them per Space.
De-selecting all colors in the Theme Picker restores the default theme.
[Spaces help article](https://resources.arc.net/hc/en-us/articles/19228064149143-Spaces-Distinct-Browsing-Areas), [theme restore article](https://resources.arc.net/hc/en-us/articles/25625261733143-How-Do-I-Restore-the-Default-Theme-for-Arc-for-Desktop).

Window translucency comes from the operating system rather than from CSS.
Arc for Windows lets the user "select either Mica or Acrylic material background from Arc menu > Settings > Appearance", and an earlier build fixed Acrylic not showing "a transparent blur effect with in Windows light theme".
[Mica and Acrylic note](https://resources.arc.net/hc/en-us/articles/22513842649623-Arc-for-Windows-2023-2026-Release-Notes).

## What Zen does

Zen ships a single raster grain tile and applies it in three places with three different treatments.
The tile is `src/zen/images/grain-bg.png`, 220 by 220 pixels, an 8-bit palette PNG with a transparency chunk.
Its mean alpha is 31.6 of 255, about 12.4 percent, and its peak alpha is 69 of 255.
Measured from [grain-bg.png](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/images/grain-bg.png).

The main browser background uses the tile with no blend mode.
`.zen-browser-grain` is an absolutely positioned overlay with `background-image: url(chrome://browser/content/zen-images/grain-bg.png)`, `pointer-events: none`, and `z-index: 1`.
Visibility is gated on a `zen-show-grainy-background` attribute, and strength is a CSS variable with a default of zero: `opacity: var(--zen-grainy-background-opacity, 0)`.
No `background-size` is set, so the tile repeats at 220 pixels.
The surrounding container sets `isolation: isolate` and `contain: content`, and its background pseudo-elements carry `will-change: background-color`.
[zen-browser-ui.css](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/common/styles/zen-browser-ui.css).

The theme picker preview adds `mix-blend-mode: hard-light`.
The welcome page uses `mix-blend-mode: overlay` at `opacity: 0.3`.
[zen-gradient-generator.css](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/spaces/zen-gradient-generator.css), [zen-welcome.css](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/welcome/zen-welcome.css).

The grain strength is a sixteen step control.
The picker rounds the texture value to sixteenths and wraps one back to zero, then writes it to `--zen-grainy-background-opacity`.
[ZenGradientGenerator.mjs](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/spaces/ZenGradientGenerator.mjs).

Zen does not use `feTurbulence` anywhere in its theme CSS.
Its one SVG filter asset is a `feFlood` plus `feMerge` underlay used with `backdrop-filter`, not a noise generator.
[zen-backdrop-filters.svg](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/common/styles/zen-backdrop-filters.svg).
Zen also sizes its gradient opacity slider to roughly 0.30 to 0.80, so its translucent surfaces keep a floor of opacity.
[theme-picker.inc](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/browser/base/content/zen-panels/theme-picker.inc).

Both products arrive at a 220 pixel palette PNG tile with a transparency chunk, and Arc's ships in 2022, before Zen's.
The two files are not byte-identical and their palettes differ.
That resemblance is an observation about format and size, not evidence that one was copied from the other.

## Why grain at all: banding

An eight-bit surface cannot render a smooth gradient across a wide, low-contrast field.
Chromium hit this directly in its own updater window.
One commit records that a dark gradient bitmap "previously contained high-frequency dither noise, causing a fuzzy appearance", while "removing dithering entirely resulted in visible 8-bit color banding across the dark gradient when rendered".
The fix regenerated the bitmap from a higher resolution source and applied "a subtle 4x4 Bayer ordered dither matrix", which "smooths out 8-bit gradient quantization steps while avoiding high-frequency grain noise".
[Chromium commit faea7b1](https://chromium.googlesource.com/chromium/src/+/faea7b1128e955bb4163391a6c92d42859032db6).

That commit states the whole tradeoff: too much high frequency noise reads as fuzzy, none reads as banded, and a low amplitude ordered dither sits between them.
It also shows the fix is a static, precomputed bitmap rather than an animated or runtime-generated effect.

WebKit's equivalent issue is still open.
Bug 90339, "Gradient do not dither", has been in the NEW state since June 30, 2012, and note that CSS gradients "look much better (no banding)" only in some encodings.
[WebKit bug 90339](https://bugs.webkit.org/show_bug.cgi?id=90339).
Automatic dithering is therefore not something the app can rely on from the engine.

## The feTurbulence parameters, and what each one costs

`feTurbulence` synthesises an image from the Perlin turbulence function and fills the entire filter primitive subregion.
[SVG 1.1 filter effects](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).
MDN notes it is Baseline and widely available, and that it operates in `linearRGB` by default unless `color-interpolation-filters` says otherwise.
[MDN feTurbulence](https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Element/feTurbulence).

`type="fractalNoise"` is the right choice for grain.
The specification separates the two types by their summations: `fractalSum` adds signed noise and is aimed at a range of −1 to 1, while `turbulence` adds absolute values and is aimed at 0 to 1.
Fractal noise therefore stays centred, while turbulence is one sided.
[SVG 1.1 feTurbulence](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).
The specification's own example uses `fractalNoise` for its fine grained samples, at `baseFrequency` 0.1 to 0.4.

`baseFrequency` is measured in cycles per user unit.
For a `background-size` equal to the SVG's own width and height, one user unit is one CSS pixel, so `baseFrequency="0.8"` is 0.8 cycles per CSS pixel.
The default is 0, which produces no variation.
[SVG 1.1 feTurbulence](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).

`numOctaves` is the cost knob.
The specification's own reference algorithm doubles the sample vector every octave (`vec[0] *= 2; vec[1] *= 2;`) and accumulates each octave at half the previous weight.
Octave n therefore has an effective frequency of `baseFrequency * 2^n`.
At `baseFrequency="0.8"`, octave 1 is 1.6 cycles per pixel and octave 3 is 6.4, both far above the 0.5 cycles per pixel Nyquist limit for a one device pixel sampling grid.
Those octaves contribute aliased per-pixel energy rather than resolvable texture, and each one is another full Perlin evaluation for each of the four channels.
[SVG 1.1 feTurbulence](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).

Measurement confirms that the higher octaves buy nothing.
The repository's shipped tile at `numOctaves="4"` and the same tile at `numOctaves="2"` were rendered at 160 by 160 in the same engine and compared.
The mean absolute difference between horizontally adjacent pixels fell only from 0.734 to 0.709 of an 8-bit step, and the luminance span fell from 0.543 to 0.527 percent of full scale.
Two octaves reproduce essentially the whole visible effect at roughly half the filter work.

`stitchTiles="stitch"` is mandatory for a repeating tile.
The specification states that with `noStitch` the result "will show clear discontinuities at the tile borders", and that with `stitch` the user agent adjusts `baseFrequency` so the tile contains an integral number of Perlin tiles.
The adjustment is picked to minimise the relative change: `lowFreq = floor(width * frequency) / width`, `hiFreq = ceil(width * frequency) / width`, and whichever of `frequency / lowFreq` and `hiFreq / frequency` is smaller.
This means the frequency the browser actually uses is not always the one you wrote.
At 160 by 160 with `baseFrequency="0.8"` the product is 128, an integer, so the requested frequency survives unchanged.
Choosing a tile size whose product with `baseFrequency` is an integer makes the texture reproducible.
[SVG 1.1 feTurbulence](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).

`seed` defaults to 0 and is truncated toward zero before use.
Setting it explicitly costs nothing and documents that the texture is meant to be stable.
[SVG 1.1 feTurbulence](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).

`color-interpolation-filters` is the parameter most easily missed.
Its initial value is `linearRGB`, while `color-interpolation` initialises to `sRGB`, and the specification notes that a filter pipeline may need either to be set explicitly to get the intended result.
[SVG 1.1 filter effects](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).
This changes the grain's actual tone, not just its gamma.
Reading the rendered tile back through a canvas gives an unpremultiplied mean luminance of 127.6 of 255 under the default `linearRGB`, and 57.0 of 255 with `color-interpolation-filters="sRGB"`.
The default therefore produces a mid grey tile, and the explicit `sRGB` setting produces a substantially darker one.
Whichever is chosen, the choice should be deliberate and written into the SVG.

Alpha is the strength control.
`feTurbulence` writes all four channels, so the tile arrives with a varying alpha as well as a varying colour.
Measured on the repository's tile: mean alpha 127.6 of 255, minimum 15.6, maximum 232, with no fully transparent pixels.
`feColorMatrix type="saturate" values="0"` removes the colour cast but leaves alpha alone.
An `feComponentTransfer` with `feFuncA type="linear"` then scales alpha and becomes the single strength knob.
The specification notes that `feColorMatrix` and `feComponentTransfer` operate on non-premultiplied data even though other primitives use premultiplied data.
[SVG 1.1 filter effects](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement).

## Blend mode: why `overlay` is the wrong default here

`background-blend-mode` blends an element's background images with each other and with its background color.
`mix-blend-mode` blends an element with its backdrop inside the same stacking context, and it creates a stacking context.
Blending an element's own layers and blending against the page are different operations, and the specification tells authors to use `background-blend-mode` for the former.
[MDN background-blend-mode](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/background-blend-mode), [MDN mix-blend-mode](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/mix-blend-mode).

`overlay` multiplies or screens depending on the backdrop value, while `hard-light` does the same depending on the source value.
`overlay` is documented as the inverse of `hard-light`, and its stated purpose is to preserve the backdrop's highlights and shadows.
[CSS Compositing and Blending Level 2](https://drafts.csswg.org/compositing-2/), [MDN mix-blend-mode](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/mix-blend-mode).

That dependence on the backdrop is exactly the problem on a flat, near-extreme surface.
Over a background near white, `overlay` can only screen the noise toward white, which compresses the result into a narrow band close to the backdrop.
Over a background near black, it can only multiply toward black, with the same compression.
The grain is strongest where the backdrop is mid toned and weakest where the surface is flat and empty, which is the opposite of what this app needs.

The repository currently sets `mix-blend-mode: overlay` on a full viewport `body::after` at `--grain-opacity: 0.05` for the light theme.
Rendered in Chromium at a device pixel ratio of 1 against `--bg: #f8f9f6`, the background pixels came back identical to the no-grain baseline: standard deviation 0.000 percent and the same minimum and maximum luminance to two decimal places.
The only measurable effect was on dark content: the solid text colour block rose from a maximum luminance of 4.02 to 4.30 percent of full scale.
In the dark theme at `--grain-opacity: 0.08` against `--bg: #171c19`, the background standard deviation was 0.029 percent.
The shipped layer therefore costs a stacking context and a full viewport blend while contributing no measurable grain to the surface it was added to, and it touches content instead.

Replacing the blend mode with plain alpha compositing and scaling alpha instead fixes this.
The same 160 pixel tile, `numOctaves="2"`, `color-interpolation-filters="sRGB"`, placed in the element's own background with `background-blend-mode: normal` and `feFuncA` slope set, measured as follows.

| Theme | `feFuncA` slope | Mean luminance shift | Luminance span | Background standard deviation |
| --- | --- | --- | --- | --- |
| `#f8f9f6` light | 0.03 | −1.42 of 255 | 3.41 of 255 | 0.528 percent |
| `#f8f9f6` light | 0.05 | −2.51 of 255 | 5.92 of 255 | 0.790 percent |
| `#f8f9f6` light | 0.08 | −4.12 of 255 | 8.35 of 255 | 1.207 percent |
| `#171c19` dark | 0.008 | +0.27 of 255 | 0.76 of 255 | 0.106 percent |
| `#171c19` dark | 0.012 | +0.42 of 255 | 1.17 of 255 | 0.158 percent |

The same tiles with `background-blend-mode: overlay` measured a background standard deviation of 0.000 percent in the light theme at every slope tested, and never above 0.017 percent in the dark theme.
On flat backgrounds the blend mode, not the opacity, is what determines whether the grain exists.

Because a single alpha composited tile always carries its own colour, it biases the surface toward that colour rather than jittering around it.
The measured light theme drift is about −1.4 to −2.5 of 255, toward the darker noise the `sRGB` setting produces.
Compensate by nudging `--bg` lighter, or by keeping the tile's colour near the background and accepting a weaker effect.
A two sided tile, one light grain layer and one dark grain layer with complementary alpha, would cancel the drift, but that recipe was not measured here and should be treated as untested.

## Paint and compositing cost

Paint is often the longest running stage in the pixel pipeline and the one to avoid.
Changing anything other than `transform` or `opacity` triggers paint, and effects that involve a blur or a shadow cost more to paint than flat fills.
[Simplify paint complexity and reduce paint areas](https://web.dev/articles/simplify-paint-complexity-and-reduce-paint-areas).

Only `transform` and `opacity` changes can be handled by the compositor alone, and the element must be on its own compositor layer for that to help.
Layers are not free: every layer's textures are uploaded to the GPU, consuming memory and bandwidth, so promotion should not be applied indiscriminately.
[Stick to compositor-only properties and manage layer count](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count).

The practical consequences for a grain layer:

A static grain tile in the background stack is painted with the background and reused.
It does not need `will-change`, and it does not need its own layer.
This is the cheapest available form of the effect, and it is the form both Arc's site and Zen's main background use.

A fixed, full viewport element with a blend mode is the expensive form.
It creates a stacking context, and its backdrop includes the scrolling content beneath it, so the blend can be re-evaluated as that content changes.
That is the shape of the current implementation, and the measurements above show it also produces no visible grain on the light theme.

`backdrop-filter` is a different and heavier tool. It blurs what is behind an element and is not needed for grain.
Apple's material documentation, which is the platform vocabulary Arc's Mica and Acrylic settings come from, describes blur materials by thickness and by whether they adapt to the interface style.
[Apple UIBlurEffect.Style](https://developer.apple.com/documentation/uikit/uiblureffect/style).
Material's dark theme guidance takes the same adaptive approach, recommending `colorSurface` and `colorOnSurface` style roles and theme aware text colors rather than hardcoded ones.
[Android Material dark theme](https://developer.android.com/develop/ui/views/theming/darktheme).

## Device pixel ratio

The grain's spatial frequency in device pixels is `baseFrequency / devicePixelRatio` cycles per device pixel, independent of tile size.
`baseFrequency` is defined per user unit, a `background-size` matching the SVG's intrinsic size maps one user unit to one CSS pixel, and the rasteriser then scales CSS pixels to device pixels.
So a 160 pixel tile at a device pixel ratio of 2, and a 320 pixel tile at a device pixel ratio of 2, put the same frequency on the device grid.

At a device pixel ratio of 1, `baseFrequency="0.8"` is 0.8 cycles per device pixel, above the 0.5 Nyquist limit.
At a ratio of 2 it is 0.4 cycles per device pixel, comfortably below it.
Retina displays should therefore look smoother than 1x displays, not harsher.
This was measured: the mean absolute difference between horizontally adjacent device pixels fell from 0.734 at a ratio of 1 to 0.575 at a ratio of 2, while the amplitude was unchanged at 0.543 and 0.542 percent of full scale.

The tile cannot be re-generated per ratio from a single CSS declaration, because `baseFrequency` lives inside the data URI.
Options are to accept the coarser Retina grain, which is cheapest and is what Arc and Zen do, or to ship a second tile behind a `min-resolution` media query and double `baseFrequency` for it.
The second option was not measured and doubles the CSS payload.

`image-rendering: pixelated` was considered as a way to stop the rasteriser smoothing an upscaled tile.
It was not tested here, and it would affect the smoothed appearance of the scaled noise in ways that need measurement before adoption.

## Data URI strategy

An SVG filter inside a CSS `background-image` data URI is rasterised by the engine as an image, so the filter runs once per rendered size rather than once per repetition.
This behaviour is consistent with the measurements above, in which a single 160 pixel tile repeated across a 400 pixel surface produced a uniform, seamless field, but it is not stated as a guarantee in the SVG or CSS specifications that were examined.
Treat it as an expectation to verify in the target engine rather than as a documented property.

`stitchTiles="stitch"` is what makes the repetition seamless, and it is the reason a procedural SVG tile is preferable to a one-off generated raster here: the tile edge continuity is handled by the engine rather than by hand.
The tradeoff is the opposite of what the Chromium commit chose for its updater window, where a precomputed bitmap avoided any filter cost at paint time.

Keep the SVG in the CSS as a data URI rather than as a separate file.
The state is tiny, the URL escaping must be done carefully, and the two characters that must be percent encoded inside the data URI are `#` in `url(#id)` and `%` in `width="100%"`.
Getting either wrong yields a tile that silently renders as blank or fully opaque, which is easy to mistake for a subtle effect.

## Recommended implementation for TalkToMe

The repository already has a grain layer at `src/talktome/static/styles.css`, so the recommendation is framed as a change to what exists rather than as a new feature.
The Electron window background color already matches the theme background, at `#171c19` and `#f8f9f6`.
No application code needs to change; the values below are CSS only.

Replace the blended overlay with a background stack, and move strength from CSS opacity into the tile's alpha.
Apply the grain to the element that owns the flat surface, so it blends against the background color rather than against the interface.

```css
:root {
  color-scheme: light;
  --bg: #f8f9f6;
  /* tile: 160x160, fractalNoise, 0.8 x 160 = 128, so stitchTiles keeps the frequency */
  --grain: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='g' color-interpolation-filters='sRGB'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' seed='7' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3CfeComponentTransfer%3E%3CfeFuncA type='linear' slope='0.035'/%3E%3C/feComponentTransfer%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E");
}

:root[data-theme="dark"] {
  --bg: #171c19;
  /* Dark surfaces read more grain per unit of luminance, so the dark theme
     overrides --grain with the same tile at feFuncA slope='0.010'
     instead of 0.035. Without this override the light tile is inherited. */
}
```

Apply it as a background layer rather than as an overlay:

```css
body {
  background-color: var(--bg);
  background-image: var(--grain);
  background-repeat: repeat;
  background-size: 160px 160px;
  background-blend-mode: normal; /* alpha compositing; no blend group */
}
```

Values, with the reasoning for each:

The tile is 160 by 160 user units. Tile size does not change the device pixel frequency, only the repetition interval and the filter cost, so this is a payload and repetition choice. `0.8 * 160 = 128` is an integer, which keeps `stitchTiles="stitch"` from adjusting the requested frequency.

`baseFrequency="0.8"` gives one noise feature roughly every 1.25 CSS pixels, which reads as fine film grain rather than as cloud or marble.
The specification's own texture example uses 0.1 to 0.4 for cloud-like results, so 0.8 is deliberately in the fine end of the range.

`numOctaves="2"` because measurement showed octaves three and four change the result by about three percent while doubling the filter work.

`seed="7"` for a stable, documentable texture. Any fixed non-zero integer works.

`color-interpolation-filters="sRGB"` so the tone is deliberate. Leaving it out selects `linearRGB` and yields a substantially lighter tile, which is what the repository currently ships.

`feColorMatrix type="saturate" values="0"` because coloured grain reads as sensor noise or a rendering fault rather than as paper.

`feFuncA` slope is the strength. The light theme starts near `0.035`, which the measurements put at roughly a 4 of 255 luminance span, and the dark theme near `0.010`. Both need visual confirmation on a real display, since a dark surface reads more grain from a smaller absolute change.

`background-blend-mode: normal` is not a downgrade from `overlay` here. On a flat, near-extreme surface, `overlay` measured as inert at every strength tested, while ordinary alpha compositing produced a controllable, visible result.

`background-size: 160px 160px` matches the SVG's intrinsic size so one user unit is one CSS pixel and `baseFrequency` keeps its stated meaning.

Keep the existing `@media (prefers-contrast: more)` rule that hides the layer, and consider also hiding it under a reduced transparency preference if translucent panels are added later.

## What not to do

Do not animate the grain.
Chromium's own text on its updater gradient separates high frequency dither noise, which reads as fuzzy, from ordered dithering, which does not.
A moving grain layer is a permanently repainting full viewport surface, and `background-position` is not a compositor-only property, so each step repaints.
[Simplify paint complexity and reduce paint areas](https://web.dev/articles/simplify-paint-complexity-and-reduce-paint-areas).

Do not run the noise at full opacity or near it.
The measured tile has a mean alpha of 0.50, so full opacity alpha composites the background roughly halfway toward the noise colour, which is a visible tint rather than a texture.

Do not put grain over body text.
The measurements above show the current overlay layer changing the solid text colour's luminance while leaving the background untouched, which is the legibility cost without the intended benefit.
Text contrast is governed by a fixed ratio requirement, and a layer that perturbs glyph pixels spends part of that budget.
[WCAG contrast minimum](https://www.w3.org/TR/WCAG21/#contrast-minimum).

Do not use `overlay` or `hard-light` on a flat surface and expect the grain to appear.
Both depend on the surrounding tone, and both measured as effectively zero on the light theme's near-white background.
Reserve them for surfaces whose backdrop genuinely varies, such as a gradient or a photographic wallpaper.

Do not add `will-change` or a forced compositor layer for a static texture.
Layers cost GPU memory and bandwidth, and the guidance is explicit that elements should not be promoted unnecessarily or without profiling.
[Stick to compositor-only properties and manage layer count](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count).

Do not raise `numOctaves` to make the grain look denser.
Above roughly one octave the added frequency is beyond the sampling grid and contributes aliased per-pixel energy, which is the shimmer rather than the texture.

Do not use `backdrop-filter` to get grain.
It blurs what is behind an element and is a heavier operation than a background image, and it is not what produces the effect described here.

## Uncertainty and sources not verified

The Arc and Zen measurements are of assets served or committed at the time of research, and both projects can change them without notice.
The Arc figure is from the current `arc.net` marketing stylesheet, which is Arc's own site but is not the Arc application; the application's grain implementation was not observed directly, only its existence as a user facing Graininess control in the release notes.

The Arc help centre blocks direct requests with a bot challenge, so its articles were read through Arc's own Zendesk help centre API rather than through the rendered pages.
The article text is Arc's, but link targets and formatting were not verified in a browser.

The Apple Human Interface Guidelines page on materials renders entirely client side and its content could not be retrieved.
The Apple claim here rests on the UIKit `UIBlurEffect.Style` documentation instead, which is first party but is API reference rather than HIG guidance.
The Material 3 site is also client side only, so the Material claim rests on the Android developer documentation for dark theme.

The WebKit bug is a bug tracker entry, not a specification, and describes one engine's behaviour rather than a requirement that applies to Chromium or Electron.

The render measurements were taken in headless Chromium at a device pixel ratio of 1 unless stated, on macOS, with `deviceScaleFactor` set by Playwright.
Electron 44 embeds Chromium, so the engine family matches, but exact versions differ and colour management settings can shift the absolute luminance numbers.
The measurements should be repeated in the actual application before the values are treated as final.

The claim that an SVG filter in a background image is rasterised once per size rather than once per tile repetition is an inference from the observed uniformity of the repeated field.
It is not stated in the SVG 1.1 filter specification or in the CSS background specifications examined, and it should be verified by profiling if paint cost becomes a concern.

The two sided tile recipe that would cancel the mean luminance drift was not rendered or measured.

`image-rendering: pixelated` as a way to control how a scaled tile is sampled was not tested.

## Sources

- [SVG 1.1 filter effects, including feTurbulence, stitchTiles, and color-interpolation-filters](https://www.w3.org/TR/SVG11/filters.html#feTurbulenceElement)
- [MDN feTurbulence](https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Element/feTurbulence)
- [MDN background-blend-mode](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/background-blend-mode)
- [MDN mix-blend-mode](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/mix-blend-mode)
- [CSS Compositing and Blending Level 2](https://drafts.csswg.org/compositing-2/)
- [web.dev: Simplify paint complexity and reduce paint areas](https://web.dev/articles/simplify-paint-complexity-and-reduce-paint-areas)
- [web.dev: Stick to compositor-only properties and manage layer count](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count)
- [Chromium commit faea7b1 on dithering the updater gradient](https://chromium.googlesource.com/chromium/src/+/faea7b1128e955bb4163391a6c92d42859032db6)
- [WebKit bug 90339: Gradient do not dither](https://bugs.webkit.org/show_bug.cgi?id=90339)
- [arc.net stylesheet and noise-light.png](https://arc.net/)
- [Arc for macOS 2022 release notes](https://resources.arc.net/hc/en-us/articles/20498417809815-Arc-for-macOS-2022-Release-Notes)
- [Arc for Windows 2023-2026 release notes](https://resources.arc.net/hc/en-us/articles/22513842649623-Arc-for-Windows-2023-2026-Release-Notes)
- [Arc Spaces help article](https://resources.arc.net/hc/en-us/articles/19228064149143-Spaces-Distinct-Browsing-Areas)
- [Arc theme restore help article](https://resources.arc.net/hc/en-us/articles/25625261733143-How-Do-I-Restore-the-Default-Theme-for-Arc-for-Desktop)
- [Zen Browser desktop repository](https://github.com/zen-browser/desktop)
- [Zen zen-browser-ui.css](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/common/styles/zen-browser-ui.css)
- [Zen grain-bg.png](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/images/grain-bg.png)
- [Zen zen-gradient-generator.css](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/spaces/zen-gradient-generator.css)
- [Zen ZenGradientGenerator.mjs](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/spaces/ZenGradientGenerator.mjs)
- [Zen theme-picker.inc](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/browser/base/content/zen-panels/theme-picker.inc)
- [Zen zen-backdrop-filters.svg](https://github.com/zen-browser/desktop/blob/4c92731b2dbbcf3f5a4dad79c09d13c38f91f774/src/zen/common/styles/zen-backdrop-filters.svg)
- [Apple UIBlurEffect.Style](https://developer.apple.com/documentation/uikit/uiblureffect/style)
- [Android Material dark theme](https://developer.android.com/develop/ui/views/theming/darktheme)
- [WCAG 2.1 contrast minimum](https://www.w3.org/TR/WCAG21/#contrast-minimum)
