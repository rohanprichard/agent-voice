import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  BOTTOM_MARGIN,
  EDGE_MARGIN,
  PILL_HEIGHT,
  PILL_WIDTH,
  PLACEMENTS,
  SHADOW_MARGIN,
  TOP_CENTER,
  TRANSCRIPT_HEIGHT,
  normalizePlacement,
  pillBounds,
} = require("../desktop/geometry.cjs");

// A MacBook display after the Dock and menu bar are removed.
const WORK_AREA = { x: 0, y: 25, width: 1512, height: 958 };

test("The window is the pill plus the shadow margin on every side", () => {
  // Every transparent pixel still takes the mouse, so the window must not be
  // larger than the pill needs. An earlier version left 24px of dead band above
  // the pill, which swallowed clicks meant for the application underneath.
  const bounds = pillBounds(WORK_AREA);
  assert.equal(bounds.width, PILL_WIDTH + SHADOW_MARGIN * 2);
  assert.equal(bounds.height, PILL_HEIGHT + SHADOW_MARGIN * 2);
});

test("The pill is centred horizontally in the work area", () => {
  const bounds = pillBounds(WORK_AREA);
  assert.equal(bounds.x + bounds.width / 2, WORK_AREA.x + WORK_AREA.width / 2);
});

test("The window sits just above the bottom of the usable area", () => {
  const bounds = pillBounds(WORK_AREA);
  assert.equal(bounds.y + bounds.height + BOTTOM_MARGIN, WORK_AREA.y + WORK_AREA.height);
});

test("A second display is measured from its own origin, not from zero", () => {
  // A display sitting to the left of the main one has a negative origin.
  const left = { x: -1920, y: 0, width: 1920, height: 1080 };
  const bounds = pillBounds(left);
  assert.equal(bounds.x + bounds.width / 2, left.x + left.width / 2);
  assert.equal(bounds.y + bounds.height + BOTTOM_MARGIN, left.y + left.height);
  assert.ok(bounds.x < 0);
});

test("Opening the transcript grows the window upward and holds the pill's bottom", () => {
  const closed = pillBounds(WORK_AREA);
  const open = pillBounds(WORK_AREA, { open: true });
  assert.equal(open.height, TRANSCRIPT_HEIGHT + SHADOW_MARGIN * 2);
  assert.equal(open.width, closed.width);
  // The bottom edge is the same, so the pill does not move on screen.
  assert.equal(open.y + open.height, closed.y + closed.height);
  assert.ok(open.y < closed.y);
});

test("Closing the transcript returns the exact starting bounds", () => {
  const closed = pillBounds(WORK_AREA);
  const reopened = pillBounds(WORK_AREA, { open: false });
  assert.deepEqual(reopened, closed);
});

test("A work area smaller than the pill never produces an off-screen box", () => {
  const tiny = { x: 0, y: 0, width: 300, height: 70 };
  const bounds = pillBounds(tiny);
  assert.equal(bounds.width, 300);
  assert.equal(bounds.height, 70);
  assert.equal(bounds.x, 0);
  // No room for the margin, so the pill takes the whole area rather than
  // hanging off the bottom or reporting a negative position.
  assert.equal(bounds.y, 0);
});

test("A display with no room for the margin does not report a negative position", () => {
  const short = { x: 10, y: 30, width: 1200, height: 140 };
  const bounds = pillBounds(short);
  assert.ok(bounds.y >= short.y);
  assert.ok(bounds.y + bounds.height <= short.y + short.height);
});

test("The transcript never asks for less space than the pill", () => {
  const bounds = pillBounds(WORK_AREA, { open: true, transcriptHeight: 40 });
  assert.equal(bounds.height, PILL_HEIGHT + SHADOW_MARGIN * 2);
});

test("Opening the transcript keeps the pill at the bottom of the window", () => {
  // Both states carry the same margin, so the pill does not shift when the
  // transcript appears: only the window's top edge moves.
  const closed = pillBounds(WORK_AREA);
  const open = pillBounds(WORK_AREA, { open: true });
  assert.equal(open.y + open.height, closed.y + closed.height);
  assert.equal(closed.y + closed.height - SHADOW_MARGIN, closed.y + PILL_HEIGHT + SHADOW_MARGIN);
});

test("A window the user dragged stays where they put it", () => {
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const bounds = pillBounds(WORK_AREA);
  const anchor = { x: 120, bottom: 600 };
  const placed = anchoredBounds(bounds, anchor, WORK_AREA);
  assert.equal(placed.x, 120);
  assert.equal(placed.y + placed.height, 600);
  assert.equal(placed.width, bounds.width);
});

test("Opening the transcript after a drag grows upward from the same bottom edge", () => {
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const anchor = { x: 300, bottom: 700 };
  const closed = anchoredBounds(pillBounds(WORK_AREA), anchor, WORK_AREA);
  const open = anchoredBounds(pillBounds(WORK_AREA, { open: true }), anchor, WORK_AREA);
  assert.equal(open.y + open.height, closed.y + closed.height);
  assert.ok(open.y < closed.y);
});

test("A remembered position from another display is pulled back on screen", () => {
  // A dragged position can be left off screen by unplugging a display, and a
  // window the user cannot reach is worse than one that moved.
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const bounds = pillBounds(WORK_AREA);
  const onScreen = anchoredBounds(bounds, { x: 99999, bottom: 99999 }, WORK_AREA);
  assert.ok(onScreen.x + onScreen.width <= WORK_AREA.x + WORK_AREA.width);
  assert.ok(onScreen.y + onScreen.height <= WORK_AREA.y + WORK_AREA.height);
  const offLeft = anchoredBounds(bounds, { x: -99999, bottom: -99999 }, WORK_AREA);
  assert.equal(offLeft.x, WORK_AREA.x);
  assert.equal(offLeft.y, WORK_AREA.y);
});

test("Without a drag the pill is placed by the work area alone", () => {
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const bounds = pillBounds(WORK_AREA);
  assert.deepEqual(anchoredBounds(bounds, null, WORK_AREA), bounds);
});

// The top center placement. The work area already excludes the menu bar, so
// the top edge of the window is below the menu bar.

test("Only the two known placements are valid", () => {
  assert.deepEqual(PLACEMENTS, ["bottom", TOP_CENTER]);
  assert.equal(normalizePlacement("bottom"), "bottom");
  assert.equal(normalizePlacement(TOP_CENTER), TOP_CENTER);
  assert.equal(normalizePlacement("notch"), "bottom");
  assert.equal(normalizePlacement(undefined), "bottom");
});

test("The top center window sits just below the usable top edge", () => {
  const bounds = pillBounds(WORK_AREA, { placement: TOP_CENTER });
  assert.equal(bounds.y, WORK_AREA.y + EDGE_MARGIN);
  assert.equal(bounds.width, PILL_WIDTH + SHADOW_MARGIN * 2);
  assert.equal(bounds.height, PILL_HEIGHT + SHADOW_MARGIN * 2);
});

test("The top center pill is centred horizontally in the work area", () => {
  const bounds = pillBounds(WORK_AREA, { placement: TOP_CENTER });
  assert.equal(bounds.x + bounds.width / 2, WORK_AREA.x + WORK_AREA.width / 2);
});

test("A second display measures the top center placement from its own origin", () => {
  const left = { x: -1920, y: 0, width: 1920, height: 1080 };
  const bounds = pillBounds(left, { placement: TOP_CENTER });
  assert.equal(bounds.x + bounds.width / 2, left.x + left.width / 2);
  assert.equal(bounds.y, left.y + EDGE_MARGIN);
  assert.ok(bounds.x < 0);
});

test("Opening the transcript at the top center grows the window downward", () => {
  const closed = pillBounds(WORK_AREA, { placement: TOP_CENTER });
  const open = pillBounds(WORK_AREA, { placement: TOP_CENTER, open: true });
  assert.equal(open.height, TRANSCRIPT_HEIGHT + SHADOW_MARGIN * 2);
  assert.equal(open.width, closed.width);
  // The top edge is the same, so the pill does not move on screen.
  assert.equal(open.y, closed.y);
  assert.ok(open.y + open.height > closed.y + closed.height);
});

test("Closing the transcript at the top center returns the exact starting bounds", () => {
  const closed = pillBounds(WORK_AREA, { placement: TOP_CENTER });
  const reopened = pillBounds(WORK_AREA, {
    placement: TOP_CENTER,
    open: false,
  });
  assert.deepEqual(reopened, closed);
});

test("The default placement stays at the bottom", () => {
  assert.deepEqual(
    pillBounds(WORK_AREA),
    pillBounds(WORK_AREA, { placement: "bottom" }),
  );
});

test("A dragged top center window keeps its top edge when the transcript opens", () => {
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const anchor = { x: 300, top: 120, bottom: 196 };
  const closed = anchoredBounds(
    pillBounds(WORK_AREA, { placement: TOP_CENTER }),
    anchor,
    WORK_AREA,
    TOP_CENTER,
  );
  const open = anchoredBounds(
    pillBounds(WORK_AREA, { placement: TOP_CENTER, open: true }),
    anchor,
    WORK_AREA,
    TOP_CENTER,
  );
  assert.equal(open.x, 300);
  assert.equal(open.y, 120);
  assert.ok(open.y + open.height > closed.y + closed.height);
});

test("A remembered top center position from another display is pulled back on screen", () => {
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const bounds = pillBounds(WORK_AREA, { placement: TOP_CENTER });
  const below = anchoredBounds(
    bounds,
    { x: 99999, top: 99999, bottom: 99999 },
    WORK_AREA,
    TOP_CENTER,
  );
  assert.ok(below.x + below.width <= WORK_AREA.x + WORK_AREA.width);
  assert.ok(below.y + below.height <= WORK_AREA.y + WORK_AREA.height);
  const above = anchoredBounds(
    bounds,
    { x: -99999, top: -99999, bottom: -99999 },
    WORK_AREA,
    TOP_CENTER,
  );
  assert.equal(above.x, WORK_AREA.x);
  assert.equal(above.y, WORK_AREA.y);
});

test("A short work area at the top center keeps the window on screen", () => {
  const short = { x: 10, y: 30, width: 1200, height: 140 };
  const bounds = pillBounds(short, { placement: TOP_CENTER });
  assert.equal(bounds.y, short.y + EDGE_MARGIN);
  assert.ok(bounds.y + bounds.height <= short.y + short.height);
});

test("An anchor with only the old bottom edge still works at the top center", () => {
  const { anchoredBounds } = require("../desktop/geometry.cjs");
  const bounds = pillBounds(WORK_AREA, { placement: TOP_CENTER });
  const placed = anchoredBounds(bounds, { x: 200, bottom: 400 }, WORK_AREA, TOP_CENTER);
  assert.equal(placed.y, 400 - bounds.height);
});
