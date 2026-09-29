"use strict";

// The menu bar mark: the same two threads as the call surface, reduced to what
// still reads at 18 pixels.
//
// A menu bar icon on macOS is a template image, meaning it is an alpha mask that
// the system draws in the correct colour for the current menu bar, including the
// dark and inverted states. So the mark is authored as black pixels with varying
// alpha and colour is deliberately absent.

const { encodePng } = require("./png.cjs");

// Roughly 1.4 points at either size, which is the usual weight for a menu bar
// glyph; heavier fills in the crossing at small sizes and reads as a blob.
const STROKE = 1.4;

/** Distance from a point to a line segment, used for anti-aliased coverage. */
function distanceToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

/**
 * Draw three smooth bends in each line.
 * The short lines stay clear at 18 pixels.
 */
function threadPaths(size) {
  const amplitude = size * 0.15;
  const centre = size / 2;
  const inset = size * 0.09;
  const points = { user: [], agent: [] };
  const steps = Math.max(24, size * 4);
  for (let step = 0; step <= steps; step++) {
    const x = inset + ((size - inset * 2) * step) / steps;
    const nx = (x - inset) / (size - inset * 2);
    const edge = Math.sin(nx * Math.PI);
    const user = Math.sin(nx * Math.PI * 3 + Math.PI + 0.12) + 0.14 * Math.sin(nx * Math.PI * 2 + (Math.PI + 0.12) * 0.5);
    const agent = Math.sin(nx * Math.PI * 3 + 0.38) + 0.14 * Math.sin(nx * Math.PI * 2 + 0.19);
    points.user.push([x, centre + user * amplitude * edge]);
    points.agent.push([x, centre + agent * amplitude * edge]);
  }
  return points;
}

/** Render the mark to RGBA pixels at the requested size. */
function threadPixels(size) {
  const pixels = Buffer.alloc(size * size * 4);
  const { user, agent } = threadPaths(size);
  const half = STROKE / 2;
  // 4x4 coverage samples per pixel, so the curves are smooth rather than jagged.
  const samples = 4;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let covered = 0;
      for (let sy = 0; sy < samples; sy++) {
        for (let sx = 0; sx < samples; sx++) {
          const px = x + (sx + 0.5) / samples;
          const py = y + (sy + 0.5) / samples;
          let near = Infinity;
          for (const path of [user, agent]) {
            for (let index = 1; index < path.length; index++) {
              const distance = distanceToSegment(
                px,
                py,
                path[index - 1][0],
                path[index - 1][1],
                path[index][0],
                path[index][1],
              );
              if (distance < near) near = distance;
            }
          }
          // Anti-aliased edge: full inside the stroke, fading over one sample.
          covered += near <= half ? 1 : near <= half + 1 / samples ? 1 - (near - half) * samples : 0;
        }
      }
      const alpha = Math.round((covered / (samples * samples)) * 255);
      const offset = (y * size + x) * 4;
      // Black with alpha, which is what a template image wants.
      pixels[offset] = 0;
      pixels[offset + 1] = 0;
      pixels[offset + 2] = 0;
      pixels[offset + 3] = alpha;
    }
  }
  return pixels;
}

const png = (size) => encodePng(size, size, threadPixels(size));

/**
 * A tray icon for Electron.
 *
 * `nativeImage` is passed in rather than required, so the pixel work can be
 * tested without starting Electron. Both scales are added as representations of
 * one image so macOS picks the right one on a Retina display.
 */
function createTrayIcon(nativeImage) {
  const image = nativeImage.createEmpty();
  image.addRepresentation({ scaleFactor: 1, buffer: png(18) });
  image.addRepresentation({ scaleFactor: 2, buffer: png(36) });
  // A template image is drawn by macOS in the menu bar's own colour.
  image.setTemplateImage(true);
  return image;
}

module.exports = { createTrayIcon, threadPixels, threadPaths };
