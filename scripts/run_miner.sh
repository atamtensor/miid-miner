#!/usr/bin/env bash
# Start the miner with settings from the environment (or a .env file next to
# this repo). Every value can also be passed as extra CLI flags, which win.
#   WALLET_NAME, WALLET_HOTKEY   wallet under ~/.bittensor/wallets (hotkey + coldkeypub.txt only)
#   NETWORK                      finney (default) | test | ws://...
#   NETUID                       54 (default; 322 on testnet)
#   AXON_PORT                    8091 (default); must be reachable from the internet
#   EXTERNAL_IP                  optional, if auto-detection picks the wrong address
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
ARGS=(--netuid "${NETUID:-54}"
      --subtensor.network "${NETWORK:-finney}"
      --wallet.name "${WALLET_NAME:-miner}"
      --wallet.hotkey "${WALLET_HOTKEY:-default}"
      --axon.port "${AXON_PORT:-8091}"
      --logging.info)
[ -n "${EXTERNAL_IP:-}" ] && ARGS+=(--axon.external_ip "$EXTERNAL_IP")
exec python neurons/miner.py "${ARGS[@]}" "$@"
