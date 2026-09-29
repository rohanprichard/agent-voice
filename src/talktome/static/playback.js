export function currentAudioEvent(event, room) {
  if (event.call_id !== room.call_id) return false;
  if (event.playback_epoch !== undefined && room.playback_epoch !== undefined &&
      event.playback_epoch !== room.playback_epoch) return false;
  if (event.kind === "greeting") return !room.turn_id;
  return Boolean(room.turn_id) && event.turn_id === room.turn_id;
}

export class AudioQueue {
  constructor(play, cancel) {
    this.play = play;
    this.cancel = cancel;
    this.items = [];
    this.seen = new Set();
    this.generation = 0;
    this.running = false;
  }

  enqueue(event) {
    if (this.seen.has(event.audio_id)) return;
    this.seen.add(event.audio_id);
    this.items.push(event);
    void this.drain();
  }

  async drain() {
    if (this.running) return;
    this.running = true;
    const generation = this.generation;
    try {
      while (this.items.length && generation === this.generation) {
        await this.play(this.items.shift());
      }
    } finally {
      if (generation === this.generation) this.running = false;
    }
  }

  clear() {
    this.generation++;
    this.items = [];
    this.seen.clear();
    this.running = false;
    this.cancel();
  }
}
