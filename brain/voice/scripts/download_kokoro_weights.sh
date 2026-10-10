#!/usr/bin/env bash
# Wave 5U §5.3 (item 2) — download the Kokoro-82M weights (gitignored).
#
# kokoro-onnx needs two files (~337MB total), NOT shipped in git
# (brain/voice/models is gitignored). Tag model-files-v1.1 is the current
# re-export used by kokoro-onnx 0.6.x. After download, verify the sha256
# below so a truncated/corrupt fetch fails LOUD instead of at first speak.
#
# Usage:  bash brain/voice/scripts/download_kokoro_weights.sh
# Then:   RAPHAEL_TTS_ENGINE=kokoro (or voice.tts_engine: kokoro) to use it.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/brain/voice/models/kokoro"
mkdir -p "$DIR"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"

MODEL="$DIR/kokoro-v1.0.onnx"
VOICES="$DIR/voices-v1.0.bin"

# sha256 digests from the model-files-v1.1 release assets (GitHub API
# `digest` field, verified 2026-10-10). A truncated/corrupt fetch fails LOUD.
MODEL_SHA="beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"
VOICES_SHA="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"

fetch() { # fetch <url> <dest> <sha256>
  local url="$1" dest="$2" sha="$3"
  if [ -s "$dest" ]; then
    echo "  already present: $dest ($(du -h "$dest" | cut -f1))"
  else
    echo "  downloading $url"
    curl -fL --retry 3 --retry-delay 2 -o "$dest" "$url"
  fi
  echo "  verifying sha256..."
  echo "$sha  $dest" | sha256sum -c -
}

echo "Kokoro-82M weights -> $DIR"
fetch "$BASE/kokoro-v1.0.onnx"  "$MODEL"  "$MODEL_SHA"
fetch "$BASE/voices-v1.0.bin"   "$VOICES" "$VOICES_SHA"
echo "done. Sizes:"
ls -la "$DIR"
echo
echo "Next: RAPHAEL_TTS_ENGINE=kokoro brain/.venv/bin/python \\"
echo "        brain/voice/scripts/kokoro_samples.py"
