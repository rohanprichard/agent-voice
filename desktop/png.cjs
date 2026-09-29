"use strict";

// A minimal PNG encoder.
//
// Electron can create a tray image from a PNG buffer or from a raw bitmap, and
// only the PNG path behaves the same on every platform. Encoding one here keeps
// the icon in code, with no image asset and no build step, which is how the rest
// of this project is put together.

const zlib = require("node:zlib");

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let value = n;
    for (let bit = 0; bit < 8; bit++) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[n] = value;
  }
  return table;
})();

function crc32(buffer) {
  let crc = -1;
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ -1) >>> 0;
}

function chunk(type, body) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(body.length);
  const typed = Buffer.concat([Buffer.from(type, "ascii"), body]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typed));
  return Buffer.concat([length, typed, crc]);
}

/**
 * Encode 8-bit RGBA pixels as a PNG.
 *
 * `pixels` is width * height * 4 bytes in RGBA order, which is the order the
 * mark renderer produces and the order PNG expects.
 */
function encodePng(width, height, pixels) {
  if (pixels.length !== width * height * 4) {
    throw new Error(`Expected ${width * height * 4} bytes, received ${pixels.length}.`);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // colour type: truecolour with alpha
  // 10, 11, 12 stay zero: deflate, adaptive filtering, no interlacing.

  // Every scanline is prefixed with its filter type. Filter 0 is "none", which
  // costs a little size and keeps this readable.
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    const from = y * width * 4;
    const to = y * (width * 4 + 1);
    raw[to] = 0;
    pixels.copy(raw, to + 1, from, from + width * 4);
  }

  return Buffer.concat([
    SIGNATURE,
    chunk("IHDR", header),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

module.exports = { crc32, encodePng };
