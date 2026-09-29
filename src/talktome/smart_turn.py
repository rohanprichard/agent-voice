"""Run Pipecat Smart Turn locally beside speech recognition."""

import hashlib
import io
import logging
import math
import threading
import time
import wave
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MODEL_REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"
MODEL_NAME = "smart-turn-v3.2-cpu.onnx"
MODEL_SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"
MODEL_BYTES = 8_679_182
MODEL_URL = (
    f"https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/{MODEL_REVISION}/{MODEL_NAME}"
)
SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 8 * SAMPLE_RATE
MAX_AUDIO_BYTES = 8 * 192_000 * 2 + 4096


class SmartTurnUnavailable(RuntimeError):
    """The model cannot classify this turn."""


class SmartTurn:
    def __init__(self, directory: Path):
        self.directory = directory / "models" / "smart-turn-v3.2"
        self.session = None
        self.features = None
        self.lock = threading.Lock()
        self.state = {"status": "not_loaded", "error": None}

    def status(self):
        return {**self.state, "model": "smart-turn-v3.2", "size_mb": 8.7}

    @staticmethod
    def _valid(path):
        return (
            path.is_file()
            and path.stat().st_size == MODEL_BYTES
            and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256
        )

    def setup(self):
        """Download the pinned model once, then load it on the CPU."""
        with self.lock:
            if self.session is not None:
                return
            try:
                import onnxruntime as ort
                from faster_whisper.feature_extractor import FeatureExtractor

                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / MODEL_NAME
                if not self._valid(path):
                    self.state = {"status": "downloading", "error": None}
                    part = path.with_suffix(".part")
                    try:
                        with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=30) as response:
                            response.raise_for_status()
                            size = 0
                            with part.open("wb") as output:
                                for chunk in response.iter_bytes(128 * 1024):
                                    size += len(chunk)
                                    if size > MODEL_BYTES:
                                        raise ValueError("The Smart Turn download has an invalid size.")
                                    output.write(chunk)
                        if not self._valid(part):
                            raise ValueError("The Smart Turn download failed its integrity check.")
                        part.replace(path)
                    finally:
                        part.unlink(missing_ok=True)
                self.state = {"status": "loading", "error": None}
                options = ort.SessionOptions()
                options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                options.inter_op_num_threads = 1
                options.intra_op_num_threads = 1
                options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                session = ort.InferenceSession(
                    str(path), sess_options=options, providers=["CPUExecutionProvider"]
                )
                inputs, outputs = session.get_inputs(), session.get_outputs()
                # The published model leaves the batch size symbolic ("s6").
                if (
                    len(inputs) != 1 or inputs[0].name != "input_features"
                    or inputs[0].shape[1:] != [80, 800]
                    or len(outputs) != 1 or outputs[0].name != "logits"
                    or outputs[0].shape[1:] != [1]
                ):
                    raise ValueError("The Smart Turn model has an unsupported interface.")
                self.features = FeatureExtractor(chunk_length=8)
                self.session = session
                self.state = {"status": "ready", "error": None}
            except Exception:
                logger.exception("Smart Turn could not load.")
                self.state = {
                    "status": "error",
                    "error": "Smart Turn is unavailable. The app will use the pause setting.",
                }

    def predict(self, audio: bytes):
        """Classify the last eight seconds without storing microphone audio."""
        import numpy as np
        from faster_whisper.audio import decode_audio

        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Send at most eight seconds of microphone audio.")
        try:
            with wave.open(io.BytesIO(audio), "rb") as source:
                rate = source.getframerate()
                frames = source.getnframes()
                if (
                    source.getnchannels() != 1 or source.getsampwidth() != 2
                    or not 8000 <= rate <= 192000 or not 0 < frames <= rate * 8
                    or len(source.readframes(frames)) != frames * 2
                ):
                    raise ValueError("Send eight seconds or less of mono 16-bit WAV audio.")
        except (wave.Error, EOFError) as exc:
            raise ValueError("Send valid WAV audio for Smart Turn.") from exc
        with self.lock:
            if self.session is None:
                raise ValueError("Smart Turn is not ready.")
            started = time.perf_counter()
            samples = decode_audio(io.BytesIO(audio), sampling_rate=SAMPLE_RATE)[-WINDOW_SAMPLES:]
            if not samples.size or not np.isfinite(samples).all():
                raise ValueError("The microphone audio is invalid.")
            samples = np.pad(samples, (WINDOW_SAMPLES - samples.size, 0)).astype(np.float32)
            # Normalize the padded waveform before the Whisper feature transform.
            samples = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
            features = self.features(samples, padding=0)[None, :, :].astype(np.float32)
            if features.shape != (1, 80, 800) or not np.isfinite(features).all():
                raise ValueError("Smart Turn could not process this audio.")
            # The pinned graph ends with Sigmoid, despite the output name "logits".
            try:
                probability = float(self.session.run(["logits"], {"input_features": features})[0][0, 0])
                if not math.isfinite(probability) or not 0 <= probability <= 1:
                    raise ValueError("Smart Turn returned an invalid probability.")
            except Exception as exc:
                self.session = None
                self.state = {
                    "status": "error",
                    "error": "Smart Turn stopped. The app will use the pause setting.",
                }
                raise SmartTurnUnavailable(self.state["error"]) from exc
            return {
                "complete": probability > 0.5,
                "probability": probability,
                "inference_ms": round((time.perf_counter() - started) * 1000, 2),
            }
