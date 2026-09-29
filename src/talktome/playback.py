"""Record audio playback without treating generated text as heard text."""

import io
import math
import wave
from collections import OrderedDict


def duration_ms(audio):
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            return source.getnframes() * 1000 / source.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError, ValueError):
        return None


def alignment_chars(alignment, duration):
    """Accept ordered character times inside the audio frame."""
    if not isinstance(alignment, dict) or duration is None:
        return []
    chars = alignment.get("chars") or []
    starts = alignment.get("charStartTimesMs", alignment.get("char_start_times_ms", []))
    lengths = alignment.get("charDurationsMs", alignment.get("char_durations_ms", []))
    if not all(isinstance(values, list) for values in (chars, starts, lengths)):
        return []
    if not (len(chars) == len(starts) == len(lengths)) or len(chars) > 16000:
        return []
    result = []
    previous = 0
    for char, start, length in zip(chars, starts, lengths):
        if not isinstance(char, str) or len(char) > 8:
            return []
        if not all(isinstance(n, (int, float)) and math.isfinite(n) for n in (start, length)):
            return []
        end = start + length
        if start < 0 or length < 0 or end < previous or end > duration + 40:
            return []
        result.append((char, end))
        previous = end
    return result


class PlaybackLedger:
    def __init__(self):
        self.frames = OrderedDict()
        self.truncated_epochs = set()

    def clear(self):
        self.frames.clear()
        self.truncated_epochs.clear()

    def register(self, audio_id, *, call_id, turn_id, epoch, audio, text="", alignment=None):
        duration = duration_ms(audio)
        chars = alignment_chars(alignment, duration)
        self.frames[audio_id] = {
            "call_id": call_id, "turn_id": turn_id, "epoch": epoch,
            "duration_ms": duration, "text": text, "chars": chars,
        }
        while len(self.frames) > 512:
            _, removed = self.frames.popitem(last=False)
            self.truncated_epochs.add(removed["epoch"])
        retained = {frame["epoch"] for frame in self.frames.values()}
        self.truncated_epochs.intersection_update(retained)

    def capture(self, call_id, epoch, receipts):
        reports = {r["audio_id"]: r for r in receipts if isinstance(r, dict) and "audio_id" in r}
        parts = []
        milliseconds = 0.0
        confidence = "complete-chunks"
        uncertain = epoch in self.truncated_epochs
        for audio_id, frame in self.frames.items():
            if frame["call_id"] != call_id or frame["epoch"] != epoch:
                continue
            if uncertain:
                break
            report = reports.get(audio_id)
            if not report:
                uncertain = True
                break
            played = report.get("played_ms", 0)
            duration = frame["duration_ms"]
            if not isinstance(played, (int, float)) or not math.isfinite(played) or duration is None:
                uncertain = True
                break
            played = max(0, min(duration, played))
            milliseconds += played
            complete = bool(report.get("completed")) and played >= duration - 1
            if frame["chars"]:
                text = "".join(char for char, end in frame["chars"] if end <= played)
                parts.append(text)
                if not complete:
                    confidence = "aligned-estimate"
                    uncertain = True
                    break
            elif complete and frame["text"]:
                parts.append(frame["text"] + " ")
            else:
                uncertain = True
                break
        text = "".join(parts)
        if uncertain and confidence == "aligned-estimate" and text and not text[-1].isspace():
            # Do not report a word that stopped before its boundary.
            text = text[: max(text.rfind(" "), text.rfind("\n")) + 1]
        return {
            "heard_text": text.strip()[:4000],
            "heard_audio_ms": round(milliseconds),
            "confidence": confidence if text.strip() else "unknown",
            "uncertain_tail": uncertain,
            "presentation_clock": "AudioContext",
        }


def interruption_context(record):
    heard = record.get("heard_text", "")
    prefix = (
        "[TalkToMe playback report. The user interrupted the previous spoken reply. "
        "Generated text may still be in your history. Do not assume the user heard it. "
    )
    if heard:
        prefix += f"The conservative played prefix was: {heard!r}. "
    else:
        prefix += "No complete spoken prefix is known. "
    return prefix + (
        "The rest may be unheard. Audio timing is an estimate, not proof of hearing. "
        "Answer the new request. Do not repeat the full reply unless the user asks.]"
    )
