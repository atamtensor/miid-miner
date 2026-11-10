#!/usr/bin/env python3
"""Offline end-to-end check of the miner's image pipeline (no chain, no wallet, no S3).

Runs the real Miner.process_image_request on a synthetic validator request built
from the bundled seed image: generate 6 variations -> identity pre-check ->
sign -> drand timelock encrypt -> store (local disk instead of the S3 bucket).

  python scripts/smoke_test.py            # mock generator: free, checks install + plumbing
  python scripts/smoke_test.py --hosted   # real hosted API call (6 images, ~$0.31 on the default model)

Exit code 0 and "SMOKE OK" when every requested variation produced a stored,
encrypted submission.
"""
import argparse
import base64
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--hosted", action="store_true", help="call the real hosted API (needs MIID_HOSTED_API_KEY)")
args = ap.parse_args()

out_dir = tempfile.mkdtemp(prefix="miid_smoke_")
os.environ["MIID_USE_S3"] = "false"          # never touch the real bucket from a test
os.environ["MIID_LOCAL_STORAGE"] = out_dir
os.environ["MIID_BACKEND"] = "hosted"
os.environ.setdefault("MIID_HOSTED_SPEND_FILE", os.path.join(out_dir, "spend.json"))
if not args.hosted:
    os.environ.setdefault("MIID_HOSTED_API_KEY", "mock")

from PIL import Image, ImageEnhance, ImageOps  # noqa: E402
from bittensor_wallet import Keypair  # noqa: E402

from MIID.protocol import IdentitySynapse, ImageRequest, VariationRequest  # noqa: E402
from MIID.miner import hosted_backend  # noqa: E402
import neurons.miner as nm  # noqa: E402

if not nm.PHASE4_AVAILABLE:
    sys.exit(f"SMOKE FAIL: image pipeline unavailable: {nm._PHASE4_ERR}")

if not args.hosted:
    def _mock(base_image, prompt, intensity):
        img = ImageOps.mirror(base_image.convert("RGB"))
        return ImageEnhance.Brightness(img).enhance({"light": 1.05, "medium": 1.1, "far": 1.2}.get(intensity, 1.1))
    hosted_backend.generate = _mock

seed = ROOT / "MIID/miner/models/seed_images/475c5c38e38b_m_doc.png"
b64 = base64.b64encode(seed.read_bytes()).decode()
QUICKNET_GENESIS, PERIOD = 1692803367, 3
target_round = int((time.time() - QUICKNET_GENESIS) // PERIOD) + 100
reqs = [
    VariationRequest(type="background_in", intensity="medium", description="indoor office background"),
    VariationRequest(type="background_out", intensity="medium", description="outdoor park background"),
    VariationRequest(type="pose_edit+lighting_edit", intensity="light", description="slight head turn, warmer light"),
    VariationRequest(type="expression_edit+background_in", intensity="medium", description="gentle smile, kitchen"),
    VariationRequest(type="lighting_edit+pose_edit", intensity="far", description="dramatic side light, three-quarter view"),
    VariationRequest(type="expression_edit", intensity="light", description="neutral to slight smile"),
]
syn = IdentitySynapse(image_request=ImageRequest(
    base_image=b64, image_filename=seed.name, variation_requests=reqs,
    target_drand_round=target_round, reveal_timestamp=int(time.time()) + 300, challenge_id="smoke_test",
))

kp = Keypair.create_from_mnemonic(Keypair.generate_mnemonic())  # throwaway, in memory only
fake = types.SimpleNamespace(wallet=types.SimpleNamespace(hotkey=kp))
fake.is_valid_image_bytes = lambda b: nm.Miner.is_valid_image_bytes(fake, b)

t0 = time.time()
subs = nm.Miner.process_image_request(fake, syn)
dt = time.time() - t0
stored = list(Path(out_dir).rglob("*.tlock"))
print(f"backend={'hosted' if args.hosted else 'mock'} submissions={len(subs)}/{len(reqs)} stored={len(stored)} "
      f"time={dt:.1f}s out={out_dir}")
for s in subs:
    print(f"  {s.variation_type:32s} {s.image_hash[:12]} {s.s3_key.split('/')[-1]}")
if args.hosted:
    print("hosted spend today:", Path(os.environ["MIID_HOSTED_SPEND_FILE"]).read_text())
ok = len(subs) == len(reqs) == len(stored) and all(p.stat().st_size > 1000 for p in stored)
print("SMOKE OK" if ok else "SMOKE FAIL")
sys.exit(0 if ok else 1)
