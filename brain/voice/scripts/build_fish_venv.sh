#!/usr/bin/env bash
# Build the isolated fish-speech inference venv (brain/voice/.venv-fish).
# Isolated on purpose: fish-speech v1.5.0 pins numpy<=1.26.4, pydantic==2.9.2,
# torch<=2.4.1 — installing into brain/.venv would downgrade the live brain stack.
# pyaudio is EXCLUDED: only tools/api_client.py imports it (not tools.api_server)
# and it needs portaudio dev headers (no sudo in this environment).
set -euo pipefail
cd /home/dami/raphael
VENV=brain/voice/.venv-fish
PY=$VENV/bin/python
echo "== [1/4] creating venv =="
uv venv "$VENV" --python 3.12
echo "== [2/4] torch 2.4.1 + torchaudio (cu124) =="
uv pip install --python "$PY" torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu124
echo "== [3/4] fish-speech v1.5.0 runtime deps (minus pyaudio) =="
uv pip install --python "$PY" \
  numpy==1.26.4 "transformers>=4.45.2" "datasets==2.18.0" "lightning>=2.1.0" \
  "hydra-core>=1.3.2" "tensorboard>=2.14.1" "natsort>=8.4.0" "einops>=0.7.0" \
  "librosa>=0.10.1" "rich>=13.5.3" "gradio>5.0.0" "wandb>=0.15.11" \
  "grpcio>=1.58.0" "kui>=1.6.0" "uvicorn>=0.30.0" "loguru>=0.6.0" \
  "loralib>=0.1.2" "pyrootutils>=1.0.4" "vector_quantize_pytorch==1.14.24" \
  "resampy>=0.4.3" "einx[torch]==0.2.2" "zstandard>=0.22.0" pydub \
  faster_whisper "modelscope==1.17.1" "funasr==1.1.5" \
  "opencc-python-reimplemented==0.1.7" silero-vad ormsgpack \
  "tiktoken>=0.8.0" "pydantic==2.9.2" cachetools soundfile
echo "== [4/4] fish-speech package itself (no-deps) =="
uv pip install --python "$PY" -e brain/voice/vendor/fish-speech --no-deps
"$PY" -c "import torch, funasr, fish_speech; print('FISH_VENV_OK torch', torch.__version__, 'cuda', torch.cuda.is_available())"
echo "BUILD_DONE"
