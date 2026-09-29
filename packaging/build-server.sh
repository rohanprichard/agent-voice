#!/bin/sh
# Freeze the local server into a single directory that can be shipped inside the
# app bundle. One directory rather than one file: the native libraries load faster
# and PyInstaller is far less likely to miss one.
set -e
cd "$(dirname "$0")/.."
rm -rf build/frozen dist/frozen
# PyInstaller drops the dist-info folders, so the bundled licenses are copied out.
uv run python scripts/third_party_licenses.py build/THIRD_PARTY_LICENSES.txt
uv run pyinstaller packaging/server.py \
  --name talktome-server \
  --noconfirm \
  --clean \
  --distpath dist/frozen \
  --workpath build/frozen \
  --specpath build \
  --collect-all faster_whisper \
  --collect-all ctranslate2 \
  --collect-all onnxruntime \
  --collect-all kokoro_onnx \
  --collect-all espeakng_loader \
  --collect-all av \
  --collect-all tokenizers \
  --collect-all keyring \
  --add-data "$PWD/src/talktome/static:talktome/static" \
  --add-data "$PWD/skills/talktome:skills/talktome" \
  --add-data "$PWD/licenses:licenses" \
  --add-data "$PWD/build/THIRD_PARTY_LICENSES.txt:licenses" \
  --add-data "$PWD/NOTICE:licenses" \
  --add-data "$PWD/LICENSE:licenses" \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --hidden-import talktome.streaming \
  --hidden-import talktome.cli \
  --hidden-import talktome.__main__ \
  --hidden-import talktome.remote \
  --hidden-import talktome.remote.cli \
  --hidden-import talktome.remote.connector \
  --hidden-import talktome.remote.daemon \
  --hidden-import talktome.remote.relay
