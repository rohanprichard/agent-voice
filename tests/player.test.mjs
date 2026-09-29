import assert from "node:assert/strict";
import test from "node:test";

import { WebAudioPlayer } from "../src/talktome/static/player.js";

/** A stand-in for the Web Audio graph, with time under the test's control. */
class FakeContext {
  constructor() {
    this.state = "running";
    this.currentTime = 0;
    this.destination = { name: "destination" };
    this.resumed = 0;
    this.sources = [];
    this.analyser = null;
    this.samples = 0;
  }

  createGain() {
    return { connected: [], connect(node) { this.connected.push(node); } };
  }

  createAnalyser() {
    this.analyser = {
      fftSize: 0,
      connect() {},
      getFloatTimeDomainData(array) {
        array.fill(this.fill ?? 0);
      },
    };
    return this.analyser;
  }

  createBufferSource() {
    const source = {
      buffer: null,
      started: null,
      stopped: false,
      onended: null,
      connect() {},
      start(when) {
        this.started = when;
        this.context.sources.push(this);
      },
      stop() {
        this.stopped = true;
      },
      context: this,
    };
    return source;
  }

  async decodeAudioData(bytes) {
    this.samples = bytes.byteLength;
    return { duration: this.duration ?? 1, bytes };
  }

  async resume() {
    this.state = "running";
    this.resumed += 1;
  }
}

function audioResponse(bytes = 8) {
  return { ok: true, arrayBuffer: async () => new ArrayBuffer(bytes) };
}

/** A player with a fake clock, a stubbed network, and no real audio. */
function build({ duration = 1 } = {}) {
  const context = new FakeContext();
  context.duration = duration;
  const player = new WebAudioPlayer({ onError: () => {} });
  player.context = context;
  player.analyser = context.createAnalyser();
  player.samples = new Float32Array(4);
  player.input = context.createGain();
  const originalFetch = globalThis.fetch;
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    return audioResponse();
  };
  return {
    player,
    context,
    urls,
    restore: () => {
      globalThis.fetch = originalFetch;
    },
  };
}

/** Resolve once the scheduled handoff timer has fired. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("A first chunk gets a short start lead", async () => {
  const { player, context, restore } = build();
  try {
    context.currentTime = 5;
    const playing = player.play("/audio/a");
    await settle();
    assert.equal(context.sources[0].started, 5.08);
    context.sources[0].onended();
    await playing;
  } finally {
    restore();
  }
});

test("Consecutive chunks are placed end to end, not started from now", async () => {
  // This is the whole reason for scheduling on the audio clock: the second chunk
  // begins exactly where the first ends, so the seam is not audible.
  const { player, context, restore } = build({ duration: 2 });
  try {
    const first = player.play("/audio/a");
    await settle();
    assert.equal(context.sources[0].started, 0.08);
    // The first chunk hands control back before its sound ends.
    context.currentTime = 2 - 0.12;
    context.sources[0].onended();
    await first;

    const second = player.play("/audio/b");
    await settle();
    assert.equal(context.sources[1].started, 2.08, "chunk two should start at chunk one's end");
    context.sources[1].onended();
    await second;
  } finally {
    restore();
  }
});

test("Cancelling stops everything scheduled and drops the timeline", async () => {
  const { player, context, restore } = build();
  try {
    const playing = player.play("/audio/a");
    await settle();
    player.cancel();
    assert.equal(context.sources[0].stopped, true);
    assert.equal(player.playing, false);
    assert.equal(player.nextStart, 0);
    // The queue is not left waiting on a chunk that will never finish.
    context.sources[0].onended?.();
    await playing;
  } finally {
    restore();
  }
});

test("The level follows the output, and reads as silence before anything plays", async () => {
  const { player, context, restore } = build();
  try {
    assert.equal(player.level(), 0, "no audio graph yet means silence");
    let firstAudioMs = null;
    const playing = player.play("/audio/a", {
      onAudible: (atMs) => { firstAudioMs = atMs; },
    });
    await settle();
    context.analyser.fill = 0;
    assert.equal(player.level(), 0);
    context.analyser.fill = 0.1;
    context.currentTime = context.sources[0].started;
    assert.ok(player.level() > 0, "a sounding chunk should register a level");
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.ok(Number.isFinite(firstAudioMs));
    context.sources[0].onended();
    await playing;
  } finally {
    restore();
  }
});

test("A level is never reported above full scale", async () => {
  const { player, context, restore } = build();
  try {
    const playing = player.play("/audio/a");
    await settle();
    context.analyser.fill = 4;
    assert.equal(player.level(), 1);
    context.sources[0].onended();
    await playing;
  } finally {
    restore();
  }
});

test("The player reports whether anything is sounding", async () => {
  const { player, context, restore } = build({ duration: 0.1 });
  try {
    let idle = 0;
    player.onIdle = () => { idle += 1; };
    assert.equal(player.playing, false);
    const playing = player.play("/audio/a");
    await settle();
    await playing;
    assert.equal(player.playing, true);
    context.sources[0].onended();
    assert.equal(player.playing, false);
    assert.equal(idle, 1);
  } finally {
    restore();
  }
});

test("A suspended audio context is resumed before the first chunk", async () => {
  const { player, context, restore } = build();
  try {
    context.state = "suspended";
    const playing = player.play("/audio/a");
    await settle();
    assert.equal(context.resumed, 1);
    context.sources[0].onended();
    await playing;
  } finally {
    restore();
  }
});

test("Audio the caller already holds is decoded without a fetch", async () => {
  // A blob URL cannot be fetched under this app's content security policy, so the
  // bytes go straight to the decoder instead.
  const { player, context, urls, restore } = build();
  try {
    const playing = player.playData({ arrayBuffer: async () => new ArrayBuffer(4) });
    await settle();
    assert.deepEqual(urls, [], "no network request should be made");
    assert.equal(context.sources.length, 1);
    context.sources[0].onended();
    await playing;
  } finally {
    restore();
  }
});
