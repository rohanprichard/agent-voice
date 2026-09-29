"""Make a synthetic microphone sample for desktop tests."""

import io
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from talktome.speech import Speech

with TemporaryDirectory() as temporary:
    audio = Speech(Path(temporary)).synthesize(
        "Hello. Please help me build a local voice application."
    )
with wave.open(io.BytesIO(audio)) as source, wave.open(sys.argv[1], "wb") as output:
    output.setparams(source.getparams())
    output.writeframes(b"\0\0" * source.getframerate())
    output.writeframes(source.readframes(source.getnframes()))
    output.writeframes(b"\0\0" * source.getframerate() * 3)
print("The synthetic microphone sample is ready.")
