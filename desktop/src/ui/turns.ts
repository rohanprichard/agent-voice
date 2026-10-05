// Speech detection and turn completion have separate thresholds.
class UserTurn {
  active = false;
  revision = 0;
  silenceMs = 0;
  speechMs = 0;
  private onsetMs = 0;
  private nextAnalysisMs = 320;

  frame(probability: number): { started: boolean; analyze: boolean; fallback: boolean } {
    let started = false;
    if (probability >= (this.active ? 0.35 : 0.5)) {
      this.revision += 1;
      this.silenceMs = 0;
      this.onsetMs += 32;
      this.speechMs += 32;
      this.nextAnalysisMs = 320;
      if (!this.active && this.onsetMs >= 96) { this.active = true; started = true; }
    } else {
      this.silenceMs += 32;
      this.onsetMs = 0;
      if (!this.active) this.speechMs = 0;
    }
    const analyze = this.active && this.silenceMs >= this.nextAnalysisMs;
    if (analyze) this.nextAnalysisMs = this.silenceMs + 640;
    return { started, analyze, fallback: this.active && this.silenceMs >= 5000 };
  }

  accepts(probability: number, revision: number): boolean {
    return this.active && revision === this.revision && this.silenceMs >= 320 && probability >= 0.65;
  }

  reset(): void {
    this.active = false;
    this.revision += 1;
    this.silenceMs = 0;
    this.speechMs = 0;
    this.onsetMs = 0;
    this.nextAnalysisMs = 320;
  }
}
