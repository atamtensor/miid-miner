# MIID miner, CPU-ready fork (Bittensor SN54)

A miner for **Bittensor subnet 54 (Yanez MIID)**. It answers validators' face-image variation challenges: it generates
the requested variations of a base face image, encrypts each one with a drand timelock, uploads it to the subnet's S3
bucket, and returns signed references.

This is a documented fork of the official reference miner,
[yanez-compliance/MIID-subnet](https://github.com/yanez-compliance/MIID-subnet) at commit `c0ade1b` (2026-10-29), MIT
licensed. It keeps the upstream protocol and validator interface unchanged. On top of the reference miner it adds:

- **A CPU-only backend.** The reference miner needs a CUDA GPU (FLUX diffusion). This fork can instead call any
  OpenAI-compatible image API, with OpenRouter as the default, so it runs on **2 vCPU / 4 GB RAM with no GPU**. The
  upstream local GPU backend is still included.
- **A hard daily spend cap** for that API.
- **Reliability fixes** to the reference miner. They are listed in [CHANGES.md](CHANGES.md).

## Quick start (CPU, hosted backend)

```bash
git clone <this repo> && cd <repo>
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install --no-deps -e .
python scripts/smoke_test.py                 # offline check, no key and no chain needed -> "SMOKE OK"
cp .env.example .env                         # fill in the wallet names and MIID_HOSTED_API_KEY
bash scripts/run_miner.sh                    # or: python neurons/miner.py --netuid 54 --wallet.name ... --wallet.hotkey ...
```

The hotkey must be registered on SN54 first (`btcli subnets register --netuid 54`). The miner only needs the hotkey
file and `coldkeypub.txt` on the machine. It never needs the coldkey or its password.

## Requirements

| | Hosted backend (default without a GPU) | Local GPU backend |
|---|---|---|
| CPU / RAM | 2 vCPU / 4 GB | 8 cores / 16 GB |
| GPU | none | CUDA, ≥ 8 GB VRAM (24 GB for FLUX.1-Kontext) |
| Disk | ~3 GB (no model weights) | ~80 GB (model weights) |
| Python | 3.10–3.12 (3.11 tested) | same |
| Install | `requirements.txt` | `requirements.txt` + `requirements-gpu.txt` |
| External service | an OpenAI-compatible image API key (default OpenRouter); you pay the provider | Hugging Face token with the [FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) licence accepted |
| Network | inbound TCP on the axon port (default 8091); outbound HTTPS to the chain, the image API, drand and S3 | same |

Optional for either backend: a local identity pre-check with AdaFace on CPU (`bash scripts/setup_adaface.sh`, ~1 GB
with torch CPU). Without it the miner submits without the pre-check, and validators still score identity themselves.

## Configuration

Settings are environment variables, read from `.env` by `scripts/run_miner.sh`. The full list with defaults is in
[.env.example](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `MIID_BACKEND` | `auto` | `hosted`, `local`, or `auto` (local GPU if CUDA is present, else hosted if a key is set) |
| `MIID_HOSTED_API_KEY` | — | API key for the hosted backend (`OPENROUTER_API_KEY` also works) |
| `MIID_HOSTED_BASE_URL` | `https://openrouter.ai/api/v1` | any OpenAI-compatible endpoint that returns images from chat completions |
| `MIID_HOSTED_MODEL` | `google/gemini-2.5-flash-image` | image-editing model (about $0.05 per image on OpenRouter, measured) |
| `MIID_HOSTED_DAILY_USD` | `1.00` | hard cap per UTC day. When it is reached, the miner answers with no submissions until the next day. `0` disables generation |
| `MIID_HOSTED_CONCURRENCY` | `3` | parallel image requests per challenge |
| `MIID_FACE_CHECK` | `auto` | `auto` (check if AdaFace is installed), `on` (required), `off` |
| `HF_TOKEN`, `MIID_MODEL` | —, `flux_klein` | local GPU backend only |
| `MIID_S3_RETRIES` | `3` | upload attempts per image before the submission is dropped |
| `MIID_EXTRA_VALIDATORS` | — | extra validator hotkeys to accept, comma-separated (the upstream whitelist is built in) |
| `NETUID` | `54` | subnet (testnet: 322) |
| `WALLET_NAME`, `WALLET_HOTKEY`, `NETWORK`, `AXON_PORT`, `EXTERNAL_IP` | `miner`, `default`, `finney`, `8091`, auto | used by `scripts/run_miner.sh` |

Standard bittensor flags (`--wallet.*`, `--axon.*`, `--subtensor.*`, `--logging.*`) work as usual and override the
environment.

**Cost.** Each challenge asks for 6 variations, so it costs about $0.31 with the default model (measured 11-2026: 6 images in 26 s). The daily cap bounds
the worst case. Check your provider's dashboard, and size the cap to the rewards you expect.

## Run with Docker

```bash
docker build -t miid-miner .
docker run -d --name miid --restart unless-stopped -p 8091:8091 \
  --env-file .env -v ~/.bittensor/wallets:/root/.bittensor/wallets:ro -v miid-data:/data miid-miner
```

The container exits non-zero if the miner's sync thread dies, so the restart policy brings it back.

## Run with pm2

```bash
pm2 start scripts/run_miner.sh --name miid --interpreter bash
```

## How it works

1. A validator sends an `IdentitySynapse` with an `ImageRequest`. It holds a base64 base face image and 6
   `VariationRequest`s (background in/out and combined pose, lighting and expression edits, each with an intensity
   and a description).
2. The backend generates one image per request. The hosted backend sends the base image and a prompt built from the
   request; the local backend runs FLUX.
3. Optionally, AdaFace drops variations that lose the person's identity (cosine similarity < 0.4).
4. Each image is hashed and signed with the hotkey, then timelock-encrypted to the validator's drand round.
5. The encrypted image is uploaded by HTTP PUT to the subnet's public-write bucket (`yanez-miid-sn54`), retrying up to
   3 times.
6. The miner returns `S3Submission`s (key, hash, signature, path signature). A failed upload is never reported.

Voice challenges are answered with no submission, as in the reference miner (its voice cloning is an unimplemented
stub). The paused screen-replay task is not implemented either.

## Data handling

- **Hosted backend.** The validator's base image and the edit prompt are sent to the configured image API provider,
  and nothing else is sent. Generated images go only to the subnet's S3 bucket, encrypted.
- **Local storage.** The miner keeps no other copies, apart from short-lived temp files for the AdaFace check, which
  are deleted after use.
- **Telemetry.** The miner sends no analytics and runs no background processes besides the miner itself.

## Verify

- `python scripts/smoke_test.py` runs the real image pipeline offline on the bundled seed image. It generates, checks,
  signs, timelock-encrypts and stores 6 variations on local disk, using a mock generator, and prints `SMOKE OK`.
- `python scripts/smoke_test.py --hosted` does the same with real API calls, about $0.31.
- In the miner log at startup, look for `Image backend: hosted | AdaFace pre-check: ...` and
  `Hosted model ... daily cap $...`. Then, per challenge, look for `Phase 4: Generated N S3 submissions`.

## Licence and attribution

MIT, the same as upstream (see [LICENSE](LICENSE)). The original copyright notices are kept in every file.
- **Upstream:** [yanez-compliance/MIID-subnet](https://github.com/yanez-compliance/MIID-subnet) @ `c0ade1b`, Copyright
  © 2023 Opentensor, © 2025 YANEZ.
- **AdaFace** (optional, fetched at setup, not bundled): [mk-minchul/AdaFace](https://github.com/mk-minchul/AdaFace),
  MIT.
- **Model weights.** None are shipped. The local backend downloads FLUX weights under their own licences: check the
  model cards, since FLUX dev-family weights are non-commercial. With the hosted backend, the provider's terms apply.

Changes from upstream are listed in [CHANGES.md](CHANGES.md).
