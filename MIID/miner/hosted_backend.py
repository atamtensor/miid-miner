# MIID/miner/hosted_backend.py
#
# CPU-only image-variation backend (added in this fork).
#
# Sends the base face image plus the validator's edit prompt to a hosted,
# OpenAI-compatible chat-completions endpoint that can return images
# (default: OpenRouter with google/gemini-2.5-flash-image), and returns a PIL
# image. No GPU, no model weights, no Hugging Face token. The base image is
# sent to the configured provider; see README "Data handling".
#
# Spend is capped per UTC day (MIID_HOSTED_DAILY_USD). Each response's
# reported cost is used when the provider returns one (OpenRouter does);
# otherwise MIID_HOSTED_COST_PER_IMAGE is charged per image. When the cap is
# reached the backend raises BudgetExceeded and the miner answers with no
# submissions until the next UTC day.

from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("MIID_HOSTED_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
MODEL = os.environ.get("MIID_HOSTED_MODEL", "google/gemini-2.5-flash-image")
TIMEOUT_S = float(os.environ.get("MIID_HOSTED_TIMEOUT", "90"))
RETRIES = int(os.environ.get("MIID_HOSTED_RETRIES", "2"))
DAILY_USD = float(os.environ.get("MIID_HOSTED_DAILY_USD", "1.00"))
COST_PER_IMAGE = float(os.environ.get("MIID_HOSTED_COST_PER_IMAGE", "0.04"))
MAX_SIDE = int(os.environ.get("MIID_HOSTED_MAX_SIDE", "1024"))
SPEND_FILE = Path(os.environ.get("MIID_HOSTED_SPEND_FILE", str(Path.home() / ".miid" / "hosted_spend.json")))

INTENSITY_HINT = {
    "light": "Make a subtle change.",
    "medium": "Make a clear but natural change.",
    "far": "Make a strong, obvious change.",
}


class BudgetExceeded(RuntimeError):
    pass


def api_key() -> str:
    return (os.environ.get("MIID_HOSTED_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


class _Spend:
    """Per-UTC-day spend counter persisted to a small JSON file (thread-safe)."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _read(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            return d if d.get("day") == self._today() else {"day": self._today(), "usd": 0.0, "images": 0}
        except Exception:
            return {"day": self._today(), "usd": 0.0, "images": 0}

    def check(self) -> None:
        with self.lock:
            d = self._read()
        if d["usd"] >= DAILY_USD:
            raise BudgetExceeded(f"hosted daily budget reached: ${d['usd']:.3f} >= ${DAILY_USD:.2f} (UTC day {d['day']})")

    def add(self, usd: float) -> dict:
        with self.lock:
            d = self._read()
            d["usd"] = round(d["usd"] + usd, 6)
            d["images"] += 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d))
            tmp.replace(self.path)
            return d


SPEND = _Spend(SPEND_FILE)


def _encode(image: Image.Image) -> str:
    img = image.convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _decode(url: str) -> Image.Image:
    if url.startswith("data:"):
        raw = base64.b64decode(url.split(",", 1)[1])
    else:
        r = requests.get(url, timeout=TIMEOUT_S)
        r.raise_for_status()
        raw = r.content
    img = Image.open(io.BytesIO(raw))
    img.load()
    return img.convert("RGB")


def generate(base_image: Image.Image, prompt: str, intensity: str) -> Image.Image:
    """One edited image for one variation request. Raises on failure."""
    key = api_key()
    if not key:
        raise RuntimeError("hosted backend: set MIID_HOSTED_API_KEY (or OPENROUTER_API_KEY)")
    SPEND.check()
    text = (
        f"Edit this photo. {prompt} {INTENSITY_HINT.get(intensity, '')} "
        "Keep the same person: identical face, facial features, age and skin tone. "
        "Photorealistic. Return only the edited image."
    )
    body = {
        "model": MODEL,
        "modalities": ["image", "text"],
        "usage": {"include": True},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": _encode(base_image)}},
        ]}],
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last: Optional[Exception] = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.post(f"{BASE_URL}/chat/completions", json=body, headers=headers, timeout=TIMEOUT_S)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            d = r.json()
            cost = (d.get("usage") or {}).get("cost")
            msg = (d.get("choices") or [{}])[0].get("message") or {}
            images = msg.get("images") or []
            # A text-only answer (e.g. a refusal) is still billed; count it.
            spent = SPEND.add(float(cost) if cost is not None else (COST_PER_IMAGE if images else 0.0))
            if not images:
                raise RuntimeError(f"no image in response (text: {(msg.get('content') or '')[:120]!r})")
            logger.info("hosted image ok (%s), day spend $%.3f / %d images", MODEL, spent["usd"], spent["images"])
            return _decode(images[0]["image_url"]["url"])
        except BudgetExceeded:
            raise
        except Exception as e:  # network error, 5xx, refusal
            last = e
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"hosted generation failed after {RETRIES + 1} attempts: {last}")
