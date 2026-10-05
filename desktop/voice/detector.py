# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy==2.3.5", "onnxruntime==1.23.2", "transformers==4.57.6"]
# ///
"""Run speech detection on the Mac. Audio stays in memory."""

import base64
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

os.environ["USE_TORCH"] = "0"
os.environ["USE_TF"] = "0"

import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor

MODELS = {
    "silero_vad.onnx": (
        (
            "https://raw.githubusercontent.com/snakers4/silero-vad/"
            "1e261b036686cd0017d500ee96acd1c4ba572a9d/src/silero_vad/data/silero_vad.onnx"
        ),
        "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    ),
    "smart-turn-v3.2-cpu.onnx": (
        (
            "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
            "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx"
        ),
        "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
    ),
}


def model_file(folder, name):
    url, expected = MODELS[name]
    target = folder / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return str(target)
    folder.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(20_000_000)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("The speech model checksum does not match.")
    temporary = target.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(target)
    return str(target)


def session(filename):
    options = ort.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    return ort.InferenceSession(
        filename, sess_options=options, providers=["CPUExecutionProvider"]
    )


class Detector:
    def __init__(self, folder):
        self.vad = session(model_file(folder, "silero_vad.onnx"))
        self.turn = session(model_file(folder, "smart-turn-v3.2-cpu.onnx"))
        self.features = WhisperFeatureExtractor(chunk_length=8)
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.pending = np.empty(0, dtype=np.float32)

    def speech(self, audio):
        self.pending = np.concatenate((self.pending, audio))
        probabilities = []
        while len(self.pending) >= 512:
            chunk = self.pending[:512].reshape(1, -1)
            self.pending = self.pending[512:]
            combined = np.concatenate((self.context, chunk), axis=1)
            output, self.state = self.vad.run(
                None,
                {
                    "input": combined,
                    "state": self.state,
                    "sr": np.array(16000, dtype=np.int64),
                },
            )
            self.context = combined[:, -64:]
            probabilities.append(float(output.reshape(-1)[0]))
        return {"probabilities": probabilities}

    def endpoint(self, audio):
        audio = audio[-128000:]
        audio = np.pad(audio, (max(0, 128000 - len(audio)), 0))
        features = self.features(
            audio,
            sampling_rate=16000,
            return_tensors="np",
            padding="max_length",
            max_length=128000,
            truncation=True,
            do_normalize=True,
        ).input_features.astype(np.float32)
        probability = self.turn.run(None, {"input_features": features})[0].reshape(-1)[
            0
        ]
        return {"probability": float(probability)}


def main():
    detector = Detector(Path(sys.argv[1]))
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        try:
            audio = np.frombuffer(
                base64.b64decode(request.get("audio", ""), validate=True), dtype="<i2"
            )
            audio = audio.astype(np.float32) / 32768.0
            if request["kind"] == "vad":
                result = detector.speech(audio)
            elif request["kind"] == "turn":
                result = detector.endpoint(audio)
            elif request["kind"] == "reset":
                detector.reset()
                result = {}
            else:
                raise ValueError("The speech detection request is not valid.")
            print(json.dumps({"id": request["id"], **result}), flush=True)
        except Exception as error:  # noqa: BLE001 - Keep a failed request from stopping the call.
            print(f"Speech detection failed: {type(error).__name__}", file=sys.stderr)
            print(
                json.dumps({"id": request["id"], "error": "Speech detection failed."}),
                flush=True,
            )


if __name__ == "__main__":
    main()
