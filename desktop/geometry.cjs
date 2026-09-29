"use strict";

// The pill and its transcript are one window. The window keeps one edge in
// place and grows away from that edge. Keep the geometry in one tested place,
// not in the window code. Sizes are in logical pixels.

// The pill itself. It is small on purpose. It floats over the user's work, and
// a wide bar competes with that work.
const PILL_WIDTH = 424;
const PILL_HEIGHT = 56;

// Transparent space around the pill for its drop shadow. The window is no
// larger than this. Every transparent pixel receives the mouse, so a larger
// window would catch a click that belongs to the application below.
const SHADOW_MARGIN = 10;

// Tall enough for several lines of a conversation, but not a chat window.
const TRANSCRIPT_HEIGHT = 320;

// The transcript panel, the second visible part of the call window. The user can
// resize it, so this is only the starting size. The panel stays right-aligned
// under its own button: the reserve is that button's target plus the gap the
// call stylesheet keeps, and the panel gap matches the gap in #surface.
const TRANSCRIPT_WIDTH = 360;
const TRANSCRIPT_RESERVE = 50;
const PANEL_GAP = 8;

// Distance from the chosen edge of the usable area to the window. The work area
// already excludes the menu bar and the Dock. The pill never enters them.
const EDGE_MARGIN = 18;

// The bottom margin keeps its old name for the existing checks. Both
// placements use the same edge margin.
const BOTTOM_MARGIN = EDGE_MARGIN;

// The two placements that the Settings screen offers.
const TOP_CENTER = "top-center";
const PLACEMENTS = ["bottom", TOP_CENTER];

/** Any value other than the top center placement means the bottom placement. */
function normalizePlacement(value) {
  return value === TOP_CENTER ? TOP_CENTER : "bottom";
}

/** Keep the window inside the usable area on small or odd displays. */
function clamp(value, low, high) {
  return Math.min(Math.max(value, low), high);
}

/**
 * Where the call window goes, given a display's work area.
 *
 * The work area already excludes the Dock and the menu bar. Its origin is not
 * (0, 0) for a second display, so every value comes from it. The window is the
 * pill plus the shadow margin on each side. The pill stays centred in its
 * window, and the shadow has space to fall.
 *
 * At the bottom placement the window sits above the lower edge of the work
 * area. At the top center placement it sits below the upper edge. Electron
 * reports no camera housing geometry, so the top center placement never claims
 * to know where a housing is. It stays below the menu bar.
 */
function pillBounds(
  workArea,
  {
    placement = "bottom",
    open = false,
    width = PILL_WIDTH,
    height = PILL_HEIGHT,
    transcriptHeight = TRANSCRIPT_HEIGHT,
    margin = SHADOW_MARGIN,
    edgeMargin = EDGE_MARGIN,
  } = {},
) {
  const boxWidth = clamp(width + margin * 2, 1, workArea.width);
  const pillHeight = open ? Math.max(transcriptHeight, height) : height;
  const boxHeight = clamp(pillHeight + margin * 2, 1, workArea.height);
  // A short work area still leaves the margin if there is room for it.
  const gap = clamp(edgeMargin, 0, Math.max(0, workArea.height - boxHeight));
  const top = normalizePlacement(placement) === TOP_CENTER;
  return {
    x: Math.round(workArea.x + (workArea.width - boxWidth) / 2),
    y: Math.round(
      top
        ? workArea.y + gap
        : workArea.y + workArea.height - boxHeight - gap,
    ),
    width: Math.round(boxWidth),
    height: Math.round(boxHeight),
  };
}

/**
 * Put a window where the user last left it.
 *
 * A drag is a choice that the surface remembers. A later resize must not undo
 * that choice. Opening the transcript changes the window height. The bottom
 * placement keeps the bottom edge and grows upward. The top center placement
 * keeps the top edge and grows downward. A display change can leave a
 * remembered position off screen, so the position is clamped.
 */
function anchoredBounds(bounds, anchor, workArea, placement = "bottom") {
  if (!anchor) return bounds;
  const x = clamp(anchor.x, workArea.x, workArea.x + workArea.width - bounds.width);
  // The anchor records both edges. A change of placement can then use the edge
  // that is now fixed.
  const top = Number.isFinite(anchor.top)
    ? anchor.top
    : anchor.bottom - bounds.height;
  const bottom = Number.isFinite(anchor.bottom)
    ? anchor.bottom
    : anchor.top + bounds.height;
  const edge =
    normalizePlacement(placement) === TOP_CENTER ? top : bottom - bounds.height;
  const y = clamp(edge, workArea.y, workArea.y + workArea.height - bounds.height);
  return { ...bounds, x: Math.round(x), y: Math.round(y) };
}

/**
 * Grow the window around the transcript panel the user asked for.
 *
 * The pill keeps its size and its anchored place. The window becomes the
 * smallest box that holds the pill and the panel, plus the shadow ring. The
 * panel is right-aligned, so its right edge stays where the button is and the
 * window grows to the left. The bottom placement keeps the bottom edge, so the
 * panel grows upward. The top center placement keeps the top edge, so the panel
 * grows downward. The work area clamps the box, and the caller gets back the
 * panel size that actually fits.
 */
function transcriptBounds(
  base,
  workArea,
  {
    open = false,
    transcriptWidth = TRANSCRIPT_WIDTH,
    transcriptHeight = TRANSCRIPT_HEIGHT,
    placement = "bottom",
    margin = SHADOW_MARGIN,
  } = {},
) {
  if (!open) {
    return { bounds: base, transcriptWidth, transcriptHeight };
  }
  // The panel width or the pill decides the window width, whichever is larger.
  const contentWidth = Math.max(PILL_WIDTH, transcriptWidth + TRANSCRIPT_RESERVE);
  const boxWidth = clamp(contentWidth + margin * 2, 1, workArea.width);
  const contentHeight = PILL_HEIGHT + PANEL_GAP + transcriptHeight;
  const boxHeight = clamp(contentHeight + margin * 2, 1, workArea.height);
  // A work area too small for the request takes what it can hold. The surface
  // is told the result so it never draws a panel larger than the window.
  const fittedWidth = clamp(
    transcriptWidth,
    1,
    Math.max(1, boxWidth - margin * 2 - TRANSCRIPT_RESERVE),
  );
  const fittedHeight = clamp(
    transcriptHeight,
    1,
    Math.max(1, boxHeight - margin * 2 - PILL_HEIGHT - PANEL_GAP),
  );
  const right = base.x + base.width;
  const x = clamp(
    Math.round(right - boxWidth),
    workArea.x,
    workArea.x + workArea.width - boxWidth,
  );
  const top = normalizePlacement(placement) === TOP_CENTER;
  const edge = top ? base.y : base.y + base.height;
  const y = clamp(
    top ? Math.round(edge) : Math.round(edge - boxHeight),
    workArea.y,
    workArea.y + workArea.height - boxHeight,
  );
  return {
    bounds: { x, y, width: Math.round(boxWidth), height: Math.round(boxHeight) },
    transcriptWidth: Math.round(fittedWidth),
    transcriptHeight: Math.round(fittedHeight),
  };
}

module.exports = {
  anchoredBounds,
  BOTTOM_MARGIN,
  EDGE_MARGIN,
  PANEL_GAP,
  PILL_HEIGHT,
  PILL_WIDTH,
  PLACEMENTS,
  SHADOW_MARGIN,
  TOP_CENTER,
  TRANSCRIPT_HEIGHT,
  TRANSCRIPT_RESERVE,
  TRANSCRIPT_WIDTH,
  normalizePlacement,
  pillBounds,
  transcriptBounds,
};
