// Draw the TalkToMe app icon with the same chat bubble and signal as mark.svg.
// The menu bar mark is a monochrome template. This icon uses the full color
// palette. Generate it as a binary so the SVG and app icon share one design.
//
//   node scripts/make-app-icon.mjs

import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { encodePng } = require("../desktop/png.cjs");

const root = fileURLToPath(new URL("..", import.meta.url));
const outDir = path.join(root, "build");
const iconset = path.join(outDir, "icon.iconset");

const BACKGROUND = [17, 24, 39];
const BUBBLE = [29, 41, 59];
const EDGE = [59, 77, 101];
const MINT = [139, 255, 183];
const CYAN = [87, 217, 255];
const VIOLET = [180, 155, 255];

// 3x3 samples per pixel. Enough that the curves and the corners are smooth.
const SAMPLES = 3;
const RADIUS = 0.22;
const STROKE = 0.043;
const BUBBLE_PATH = [
  [0.275, 0.245], [0.725, 0.245], [0.785, 0.305], [0.785, 0.565],
  [0.725, 0.625], [0.535, 0.625], [0.365, 0.765], [0.365, 0.625],
  [0.275, 0.625], [0.215, 0.565], [0.215, 0.305],
];
const SIGNAL_PATH = [
  [0.285, 0.445], [0.355, 0.445], [0.405, 0.365], [0.49, 0.535],
  [0.575, 0.365], [0.63, 0.49], [0.68, 0.425], [0.735, 0.425],
];

function distanceToPath(x, y, points) {
  let nearest = Infinity;
  for (let index = 1; index < points.length; index++) {
    const [ax, ay] = points[index - 1];
    const [bx, by] = points[index];
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / lengthSquared));
    nearest = Math.min(nearest, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
  }
  return nearest;
}

function insideBubble(x, y) {
  let inside = false;
  for (let i = 0, j = BUBBLE_PATH.length - 1; i < BUBBLE_PATH.length; j = i++) {
    const [xi, yi] = BUBBLE_PATH[i];
    const [xj, yj] = BUBBLE_PATH[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function insideRoundedSquare(x, y) {
  const low = RADIUS;
  const high = 1 - RADIUS;
  const cx = x < low ? low : x > high ? high : x;
  const cy = y < low ? low : y > high ? high : y;
  return Math.hypot(x - cx, y - cy) <= RADIUS;
}

/** The colour at a point in 0..1 space, or null outside the icon. */
function sample(x, y) {
  if (!insideRoundedSquare(x, y)) return null;
  if (distanceToPath(x, y, SIGNAL_PATH) <= 0.025) {
    if (x < 0.47) return MINT;
    if (x < 0.62) return CYAN;
    return VIOLET;
  }
  if (distanceToPath(x, y, [...BUBBLE_PATH, BUBBLE_PATH[0]]) <= 0.012) return EDGE;
  return insideBubble(x, y) ? BUBBLE : BACKGROUND;
}

/** Render one size, 0..255 RGBA. */
function render(size) {
  const pixels = Buffer.alloc(size * size * 4);
  const total = SAMPLES * SAMPLES;
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SAMPLES; sy++) {
        for (let sx = 0; sx < SAMPLES; sx++) {
          const colour = sample((px + (sx + 0.5) / SAMPLES) / size, (py + (sy + 0.5) / SAMPLES) / size);
          if (!colour) continue;
          r += colour[0]; g += colour[1]; b += colour[2]; a += 255;
        }
      }
      const offset = (py * size + px) * 4;
      if (a > 0) {
        pixels[offset] = Math.round(r / (a / 255));
        pixels[offset + 1] = Math.round(g / (a / 255));
        pixels[offset + 2] = Math.round(b / (a / 255));
      }
      pixels[offset + 3] = Math.round(a / total);
    }
  }
  return pixels;
}

rmSync(iconset, { recursive: true, force: true });
mkdirSync(iconset, { recursive: true });
for (const [size, name] of [
  [16, "icon_16x16.png"], [32, "icon_16x16@2x.png"],
  [32, "icon_32x32.png"], [64, "icon_32x32@2x.png"],
  [128, "icon_128x128.png"], [256, "icon_128x128@2x.png"],
  [256, "icon_256x256.png"], [512, "icon_256x256@2x.png"],
  [512, "icon_512x512.png"], [1024, "icon_512x512@2x.png"],
]) {
  writeFileSync(path.join(iconset, name), encodePng(size, size, render(size)));
}
execFileSync("iconutil", ["-c", "icns", iconset, "-o", path.join(outDir, "icon.icns")]);
console.log(`wrote ${path.relative(root, path.join(outDir, "icon.icns"))}`);
