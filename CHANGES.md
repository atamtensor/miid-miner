# Changes from upstream

The base is [yanez-compliance/MIID-subnet](https://github.com/yanez-compliance/MIID-subnet) at commit `c0ade1b`
(2026-10-29). The miner files are the same as at `fb3d4b4`, since the last three upstream commits touch only validator
code. The protocol (`MIID/protocol.py`) and the validator-facing behaviour are unchanged. Every change is marked
`Fork:` in the code.

## Added

- **Hosted backend, CPU-only** (`MIID/miner/hosted_backend.py`).
  - Sends the base image and prompt to an OpenAI-compatible chat-completions image API. The default is OpenRouter
    with `google/gemini-2.5-flash-image`.
  - Retries with backoff, uses a per-request timeout, and generates the 6 variations in parallel.
  - Keeps a persistent per-UTC-day spend cap (`MIID_HOSTED_DAILY_USD`) based on the cost the provider reports.
  - Selected with `MIID_BACKEND=hosted`, or automatically on a machine without CUDA when a key is set.
- **Docker image** (`Dockerfile`), **start script** (`scripts/run_miner.sh`), **AdaFace installer**
  (`scripts/setup_adaface.sh`), and an **offline smoke test** (`scripts/smoke_test.py`).
- **Split requirements:**
  - `requirements.txt` is the base, with no torch.
  - `requirements-gpu.txt` covers the local FLUX backend.
  - `requirements-adaface.txt` covers the optional pre-check.
- **`MIID_EXTRA_VALIDATORS`** lets you accept new validator hotkeys without editing code.

## Fixed (reliability)

| Upstream behaviour | Fix |
|---|---|
| One failed variation re-raised, so the miner returned **no** submissions for the whole challenge (`generate_variations`) | Each variation is handled separately; failures are skipped and the rest are submitted |
| A random base model was picked per request while only one pipeline was cached, so ~2/3 of requests reloaded a 4–12B model | Default is one fixed model (`MIID_MODEL_RANDOM=0`); set it to `1` to restore |
| A missing AdaFace checkout made the image-generator import fail, which silently disabled **all** image generation | AdaFace is optional (`MIID_FACE_CHECK=auto/on/off`); its status is logged at startup |
| The AdaFace checkpoint was reloaded from disk for every variation, and temp files were never deleted | The model is loaded once and cached; temp files are removed |
| One S3 PUT attempt; on failure the image was written to local disk and **the S3 key was still returned** (a submission validators can never fetch) | Retries with backoff; on final failure the submission is dropped (`MIID_LOCAL_FALLBACK=1` restores the old behaviour) |
| Timelock encryption converted the validator's absolute drand round to a relative block count, which takes two network fetches. The round can move between those fetches, so the ciphertext could target a different round than the one the validator decrypts, and an unreachable drand relay failed every submission | Encrypts straight to the validator's round with `bittensor_drand.encrypt_at_round`, offline, and checks the round |
| Without timelock, **unencrypted** images were uploaded to the public bucket | Skipped unless `MIID_ALLOW_UNENCRYPTED=1` (sandbox only) |
| Minutes of blocking generation ran inside the async axon handler | Runs in a worker thread with a lock, and stops before the validator's timeout |
| One `sync()` exception ended the metagraph resync loop for the life of the process | Errors are caught per iteration and retried |
| The main loop kept printing "running" after the sync thread died | Exits non-zero so pm2, systemd or Docker restarts it |
| `priority()` raised for a whitelisted hotkey that is not in the metagraph | Returns 0 |
| `--netuid` defaulted to 1 | Defaults to 54 (`NETUID` env) |
| `neurons/miner.py` needed `pip install -e .` to import `MIID` | Adds the repo root to `sys.path` |

## Removed (not needed by a miner)

- Validator code (`neurons/validator.py`, `MIID/validator/`, `MIID/base/validator.py`, `MIID/api/`), datasets, the
  paused screen-replay capture guide, test utilities, and the upstream `scripts/miner/setup.sh` (which ran `apt upgrade`
  as root).
- `MIID/__init__.py` no longer imports the validator and api packages.
- The reference miner's paused screen-replay helper methods are kept unchanged in `neurons/miner.py`. They do nothing,
  as upstream.
