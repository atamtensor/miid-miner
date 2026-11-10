#!/usr/bin/env bash
# Optional: install the AdaFace identity pre-check (CPU is fine).
# Fetches the AdaFace code (MIT, github.com/mk-minchul/AdaFace) and the IR-50
# MS1MV2 checkpoint (~170 MB, Google Drive id from the upstream MIID docs).
# Without it the miner still runs and submits without the local pre-check.
set -euo pipefail
cd "$(dirname "$0")/.."
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-adaface.txt  # CPU torch (no CUDA download)
if [ ! -d MIID/miner/AdaFace ]; then
  git clone --depth 1 https://github.com/mk-minchul/AdaFace.git MIID/miner/AdaFace
fi
mkdir -p MIID/miner/AdaFace/pretrained
CKPT=MIID/miner/AdaFace/pretrained/adaface_ir50_ms1mv2.ckpt
[ -f "$CKPT" ] || gdown 1eUaSHG4pGlIZK7hBkqjyp2fc2epKoBvI -O "$CKPT"
python -c "from MIID.miner.image_generator import face_check_status as s; print('AdaFace:', s())"
